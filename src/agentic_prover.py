"""
agentic_prover.py

Leanstral + MCP agentic prover using Mistral's Conversations API (run_async).

Leanstral drives the proving loop autonomously via tool calls:
  - MCP tools (lean_diagnostic_messages, lean_goal, etc.) for reading Lean state
  - Custom Python functions (apply_tactic, get_current_proof_state) for writing
    tactics and querying the current state

The Python controller owns:
  - Working file management (via ProofFileController)
  - Checkpoint save/restore on tactic application
  - Final verification via lake build (MCP is guidance, not truth)

Usage:
  from agentic_prover import prove_theorem_agentic
  result = prove_theorem_agentic(theorem_with_sorry)
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from dotenv import load_dotenv
from pathlib import Path

from lean_verifier import verify
from mcp_runtime import PROJECT_ROOT, open_mistral_run_context
from proof_file_controller import ProofFileController

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODEL = "labs-leanstral-2603"
TIMEOUT_MS = 120_000  # 2 minutes for the full run_async conversation
DEFAULT_MAX_STEPS = 12  # not enforced directly — run_async manages its own loop

STOP_PROOF_COMPLETE = "proof_complete"
STOP_PROOF_INCOMPLETE = "proof_incomplete"
STOP_RUN_ERROR = "run_error"
STOP_TIMEOUT = "timeout"

# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------

def _log(on_log, stage: str, message: str, data: str | None = None, status: str = "done"):
    """Emit a pipeline log entry."""
    if on_log:
        on_log({"stage": stage, "message": message, "data": data, "status": status})
    else:
        print(f"[agentic] {stage}: {message}")


# ---------------------------------------------------------------------------
# System prompt for Leanstral
# ---------------------------------------------------------------------------

AGENTIC_INSTRUCTIONS_TEMPLATE = """\
You are Leanstral, an expert Lean 4 prover. You have access to lean-lsp-mcp
tools and a custom apply_tactic tool for writing proofs.

You are given a Lean 4 theorem with `sorry` as a placeholder proof.
Your task is to find a complete tactic proof that Lean accepts.

## Workflow

1. Use lean_goal to inspect the initial goal at line {goal_line} of {file_path}.
2. Call apply_tactic with a tactic block to replace sorry.
3. Use lean_diagnostic_messages on {file_path} to check for errors.
4. If there are errors, call apply_tactic again with a corrected tactic.
5. If there are NO errors and NO "sorry" warnings, the proof is complete — STOP.

## Tactic guidance

- Simple arithmetic: norm_num or decide
- Field arithmetic (+, -, *, /, ⁻¹): field_simp [...] then ring
- Equalities from hypotheses: exact h or linarith
- Existential goals: use <witness> then prove

## Screening multiple tactics

When you are uncertain which tactic will work, use lean_multi_attempt
before apply_tactic. Pass the file path, the tactic line number, and a
list of 3-5 candidate tactic snippets. The tool returns which candidates
compiled successfully. Then call apply_tactic with the best candidate.

Use lean_multi_attempt when:
- You are choosing between field_simp, ring, simp, or norm_num
- The goal contains Real.rpow and you want to screen rpow lemmas
- A previous apply_tactic call failed and you need alternatives
- The goal structure is unfamiliar

Do NOT use lean_multi_attempt for trivial goals where you are confident
in the tactic (e.g., exact h, norm_num on arithmetic).

## Searching for Mathlib lemmas

When you are stuck or need a specific lemma, use the search tools:
- lean_leansearch: describe what you need in plain English
  (e.g., "rpow addition rule for positive reals")
- lean_loogle: search by type signature pattern
  (e.g., "Real.rpow _ _ * Real.rpow _ _ = Real.rpow _ _")

Use search when:
- field_simp leaves a residual goal you don't recognize
- You need a specific rpow or log lemma name
- The goal involves Mathlib types you're unsure about

## Rules

- Do NOT use sorry.
- Keep tactic blocks concise.
- If you cannot find a proof after a few attempts, say so and stop.
- STOP as soon as lean_diagnostic_messages shows no errors and no sorry warnings.
"""


def _build_instructions(file_path: str, goal_line: int) -> str:
    """Inject runtime paths into the agent prompt without using format()."""
    return (
        AGENTIC_INSTRUCTIONS_TEMPLATE
        .replace("{file_path}", file_path)
        .replace("{goal_line}", str(goal_line))
    )


# ---------------------------------------------------------------------------
# Tool function factory
# ---------------------------------------------------------------------------

def _make_apply_tactic(controller: ProofFileController):
    """
    Create the apply_tactic closure bound to a ProofFileController.

    The function writes the tactic to the working file and returns immediately.
    It does NOT query MCP — Leanstral should use its native lean-lsp-mcp tools
    (lean_diagnostic_messages, lean_goal) via the persistent RunContext session
    to check the result. This avoids spawning a new lean-lsp-mcp subprocess
    per tactic application.

    Returns (apply_tactic_fn, tactic_call_log).
    """
    tactic_call_log: list[dict[str, Any]] = []

    def apply_tactic(tactic: str) -> str:
        """Replace the proof tactic block in the working Lean file.

        Writes the tactic to the file. After calling this, use
        lean_diagnostic_messages to check for errors and lean_goal
        to inspect remaining goals.

        Args:
            tactic: A Lean 4 tactic or tactic block. Examples: "ring",
                    "field_simp [ne_of_gt hc]", "norm_num", "exact hspend"
        """
        tactic_call_log.append({"tactic": tactic})

        try:
            controller.replace_tactic_block(tactic)
        except ValueError as exc:
            return f"ERROR: Invalid tactic block — {exc}"

        return (
            f"Tactic written to {controller.mcp_file_path}. "
            f"Use lean_diagnostic_messages to check for errors."
        )

    return apply_tactic, tactic_call_log


# ---------------------------------------------------------------------------
# Core async implementation
# ---------------------------------------------------------------------------

async def _prove_theorem_agentic_async(
    theorem_with_sorry: str,
    on_log: callable | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict[str, Any]:
    """
    Run the Leanstral+MCP agentic proving loop via Mistral's run_async.

    1. Initialize working file via ProofFileController
    2. Register custom tool functions + MCP tools via RunContext
    3. Let Leanstral drive the loop via run_async
    4. Final verification via lake build
    """
    from mistralai.client import Mistral
    from mistralai.client.models.completionargs import CompletionArgs

    controller = ProofFileController()
    start_time = time.time()
    try:
        # --- Step 1: Initialize working file ---
        _log(on_log, "agentic_init", "Initializing working proof file...", status="running")
        controller.initialize(theorem_with_sorry)
        _log(
            on_log, "agentic_init",
            f"Working file: {controller.mcp_file_path}",
            data=controller.current_lean_code,
            status="done",
        )

        # --- Step 2: Set up Mistral RunContext with tools ---
        _log(on_log, "agentic_setup", "Setting up Leanstral + MCP tools...", status="running")

        apply_tactic_fn, tactic_call_log = _make_apply_tactic(controller)
        client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

        instructions = _build_instructions(
            file_path=controller.mcp_file_path,
            goal_line=controller.goal_query_line,
        )

        user_prompt = (
            f"Prove this Lean 4 theorem:\n\n"
            f"```lean\n{theorem_with_sorry.strip()}\n```\n\n"
            f"The theorem is loaded in {controller.mcp_file_path}. "
            f"Use lean_goal at line {controller.goal_query_line} to see the initial goal, "
            f"then call apply_tactic with a tactic to prove it, "
            f"then use lean_diagnostic_messages to verify."
        )

        # --- Step 3: Run the agentic loop ---
        _log(on_log, "agentic_run", "Leanstral proving loop started...", status="running")
        stop_reason = STOP_PROOF_INCOMPLETE
        model_text = ""
        tool_trace_entries = []

        steps_used = 0
        run_ctx = None

        try:
            async with open_mistral_run_context(model=MODEL) as run_ctx:
                run_ctx.register_func(apply_tactic_fn)

                _log(on_log, "agentic_setup",
                     f"Tools registered: {len(run_ctx.get_tools())} total",
                     status="done")

                result = await client.beta.conversations.run_async(
                    run_ctx=run_ctx,
                    inputs=user_prompt,
                    instructions=instructions,
                    completion_args=CompletionArgs(
                        temperature=1.0,
                        max_tokens=32000,
                    ),
                    timeout_ms=TIMEOUT_MS,
                )

                # Extract results
                steps_used = run_ctx.request_count

                for entry in result.output_entries:
                    entry_type = getattr(entry, "type", type(entry).__name__)
                    trace_entry = {"type": entry_type}
                    if hasattr(entry, "name"):
                        trace_entry["name"] = entry.name
                    if hasattr(entry, "arguments"):
                        trace_entry["arguments"] = str(entry.arguments)[:500]
                    if hasattr(entry, "result"):
                        trace_entry["result"] = str(entry.result)[:500]
                    if hasattr(entry, "content"):
                        trace_entry["content"] = str(entry.content)[:500]
                    tool_trace_entries.append(trace_entry)

                try:
                    model_text = result.output_as_text
                except (ValueError, AttributeError):
                    model_text = ""

        except asyncio.TimeoutError as exc:
            steps_used = getattr(run_ctx, "request_count", steps_used)
            current_tactics = controller.current_tactic_block
            current_code = controller.current_lean_code
            partial_verification = None

            if current_tactics != "sorry":
                try:
                    partial_verification = verify(current_code)
                except Exception:
                    partial_verification = None

            elapsed = time.time() - start_time
            summary_parts = [
                "Leanstral agentic prover timed out before finishing the proving loop.",
            ]
            if partial_verification and partial_verification["success"]:
                summary_parts.append("The partial proof nonetheless verified by lake build.")
            elif current_tactics != "sorry":
                summary_parts.append("Returning the latest tactic block and verification output.")
            else:
                summary_parts.append("No proof progress beyond the initial sorry placeholder was captured.")

            error_message = f"run_async timed out after {TIMEOUT_MS}ms"
            warnings = list(partial_verification.get("warnings", [])) if partial_verification else []
            warnings.append(error_message)

            return {
                "success": bool(partial_verification and partial_verification["success"]),
                "strategy": model_text,
                "proof_tactics": current_tactics,
                "full_lean_code": current_code,
                "errors": (
                    partial_verification.get("errors", [])
                    if partial_verification
                    else [error_message]
                ),
                "warnings": warnings,
                "tool_trace": tool_trace_entries,
                "tactic_calls": tactic_call_log,
                "steps_used": steps_used,
                "mcp_enabled": True,
                "agent_summary": " ".join(summary_parts),
                "stop_reason": STOP_TIMEOUT,
                "output_lean": (
                    partial_verification.get("output_lean")
                    if partial_verification
                    else None
                ),
                "elapsed_seconds": elapsed,
                "partial": True,
            }
        except Exception as exc:
            _log(on_log, "agentic_run", f"run_async error: {exc}", status="error")
            stop_reason = STOP_RUN_ERROR
            elapsed = time.time() - start_time
            return {
                "success": False,
                "strategy": "",
                "proof_tactics": controller.current_tactic_block,
                "full_lean_code": controller.current_lean_code,
                "errors": [str(exc)],
                "warnings": [],
                "tool_trace": tool_trace_entries,
                "tactic_calls": tactic_call_log,
                "steps_used": 0,
                "mcp_enabled": True,
                "agent_summary": f"run_async failed: {exc}",
                "stop_reason": stop_reason,
                "output_lean": None,
                "elapsed_seconds": elapsed,
                "partial": False,
            }

        _log(on_log, "agentic_run",
             f"Leanstral loop completed ({steps_used} API round-trips, {len(tactic_call_log)} tactic calls)",
             status="done")

        # --- Step 4: Check if proof looks complete (pre-verification) ---
        current_tactics = controller.current_tactic_block
        if "sorry" in current_tactics:
            stop_reason = STOP_PROOF_INCOMPLETE
            _log(on_log, "agentic_check", "Proof still contains sorry", status="error")
        else:
            stop_reason = STOP_PROOF_COMPLETE
            _log(on_log, "agentic_check", "Proof appears complete (no sorry)", status="done")

        # --- Step 5: Final verification via lake build ---
        _log(on_log, "agentic_verify", "Running final lake build verification...", status="running")
        verification = verify(controller.current_lean_code)

        if verification["success"]:
            stop_reason = STOP_PROOF_COMPLETE
            _log(on_log, "agentic_verify", "Verified — lake build passed", status="done")
        else:
            if stop_reason == STOP_PROOF_COMPLETE:
                stop_reason = STOP_PROOF_INCOMPLETE  # MCP said done but lake disagreed
            error_preview = str(verification["errors"][:2])
            _log(on_log, "agentic_verify",
                 f"Verification failed: {error_preview}",
                 data=str(verification["errors"]),
                 status="error")

        elapsed = time.time() - start_time
        success = verification["success"]

        summary_parts = [
            f"Leanstral agentic prover: {steps_used} API round-trips, "
            f"{len(tactic_call_log)} tactic applications.",
        ]
        if success:
            summary_parts.append("Proof verified by lake build.")
        else:
            summary_parts.append(f"Proof not verified. Stop reason: {stop_reason}.")

        return {
            "success": success,
            "strategy": model_text,
            "proof_tactics": current_tactics,
            "full_lean_code": controller.current_lean_code,
            "errors": verification["errors"],
            "warnings": verification["warnings"],
            "tool_trace": tool_trace_entries,
            "tactic_calls": tactic_call_log,
            "steps_used": steps_used,
            "mcp_enabled": True,
            "agent_summary": " ".join(summary_parts),
            "stop_reason": stop_reason,
            "output_lean": verification.get("output_lean"),
            "elapsed_seconds": elapsed,
            "partial": False,
        }
    finally:
        controller.cleanup()


# ---------------------------------------------------------------------------
# Public sync API
# ---------------------------------------------------------------------------

def prove_theorem_agentic(
    theorem_with_sorry: str,
    on_log: callable | None = None,
    max_steps: int = DEFAULT_MAX_STEPS,
) -> dict[str, Any]:
    """
    Agentic prover using Leanstral + MCP via Mistral's Conversations API.

    Leanstral autonomously calls lean-lsp-mcp tools and custom Python functions
    to build a proof interactively. Final verification is via lake build.

    Args:
        theorem_with_sorry: Complete Lean 4 theorem with sorry placeholder.
        on_log: Optional callback for pipeline log entries.
        max_steps: Advisory step budget (actual loop is managed by run_async).

    Returns:
        dict with keys: success, strategy, proof_tactics, full_lean_code,
        errors, warnings, tool_trace, steps_used, mcp_enabled, agent_summary,
        stop_reason, output_lean, elapsed_seconds.
    """
    return asyncio.run(
        _prove_theorem_agentic_async(
            theorem_with_sorry=theorem_with_sorry,
            on_log=on_log,
            max_steps=max_steps,
        )
    )


if __name__ == "__main__":
    print("Run tests via: python tests/test_agentic_examples.py")
