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
  - Final verification via the local Lean compiler (MCP is guidance, not truth)

Usage:
  from agentic_prover import prove_theorem_agentic
  result = prove_theorem_agentic(theorem_with_sorry)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, cast

from dotenv import load_dotenv

from lean_verifier import verify
from mcp_runtime import PROJECT_ROOT, open_mistral_run_context
from proof_file_controller import ProofFileController
from prover_backend import register_prover

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
RETRYABLE_STATUS_CODES = {429, 503}
BACKOFF_DELAYS_SECONDS = (2, 4, 8, 16)
MAX_CONSECUTIVE_APPLY_WITHOUT_DIAGNOSTICS = 5
TRACE_SCHEMA_VERSION = 2
CIRCUIT_BREAKER_WARNING = (
    "CIRCUIT BREAKER TRIGGERED: You must use lean_diagnostic_messages to check your work "
    "before applying more tactics."
)

# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


def _log(on_log, stage: str, message: str, data: str | None = None, status: str = "done"):
    """Emit a pipeline log entry."""
    if on_log:
        on_log({"stage": stage, "message": message, "data": data, "status": status})
    else:
        print(f"[agentic] {stage}: {message}")


@dataclass
class AgenticToolTracker:
    """Track tool usage patterns to prevent runaway local-tool loops."""

    consecutive_apply_without_diagnostics: int = 0
    total_apply_calls: int = 0
    total_diagnostic_calls: int = 0
    circuit_breaker_hits: int = 0

    def should_block_apply(self) -> bool:
        return (
            self.consecutive_apply_without_diagnostics >= MAX_CONSECUTIVE_APPLY_WITHOUT_DIAGNOSTICS
        )

    def note_apply_tactic_executed(self) -> None:
        self.total_apply_calls += 1
        self.consecutive_apply_without_diagnostics += 1

    def note_diagnostic_check(self) -> None:
        self.total_diagnostic_calls += 1
        self.consecutive_apply_without_diagnostics = 0

    def note_circuit_breaker(self) -> None:
        self.circuit_breaker_hits += 1


@dataclass
class TraceRecorder:
    """Capture rich tool-call traces and tactic-attempt outcomes."""

    entries: list[dict[str, Any]] = field(default_factory=list)
    sequence_id: int = 0
    latest_kernel_errors: list[str] = field(default_factory=list)
    latest_kernel_warnings: list[str] = field(default_factory=list)
    pending_tactic_log_index: int | None = None

    def append_message_output(self, *, request_index: int, content: Any) -> None:
        text = _truncate_text(content, limit=1000)
        if not text:
            return
        self.entries.append(
            {
                "sequence_id": self._next_sequence_id(),
                "request_index": request_index,
                "type": "message.output",
                "content": text,
            }
        )

    def append_tool_call(
        self,
        *,
        request_index: int,
        tool_call_id: str,
        tool_name: str,
        tool_kind: str,
        arguments: Any,
        result_text: Any,
        status: str,
        blocked: bool = False,
        diagnostic_payload: dict[str, Any] | None = None,
    ) -> None:
        entry = {
            "sequence_id": self._next_sequence_id(),
            "request_index": request_index,
            "type": "tool_call",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "tool_kind": tool_kind,
            "arguments": _normalize_tool_arguments(arguments),
            "result_text": _truncate_text(result_text, limit=1500),
            "status": status,
            "blocked": blocked,
            "kernel_errors": [],
            "kernel_warnings": [],
        }
        if diagnostic_payload is not None:
            entry["diagnostic_payload"] = diagnostic_payload
            entry["kernel_errors"] = list(diagnostic_payload.get("errors", []))
            entry["kernel_warnings"] = list(diagnostic_payload.get("warnings", []))
        self.entries.append(entry)

    def note_tactic_attempt(self, tactic_call_log: list[dict[str, Any]], tactic: str) -> None:
        if self.pending_tactic_log_index is not None:
            previous = tactic_call_log[self.pending_tactic_log_index]
            if previous.get("successful") is None:
                previous["successful"] = False
                previous["resolution"] = "superseded_before_diagnostics"

        tactic_call_log.append(
            {
                "attempt_index": len(tactic_call_log) + 1,
                "tactic": tactic,
                "tactic_preview": _preview_tactic(tactic),
                "triggering_errors": list(self.latest_kernel_errors),
                "triggering_warnings": list(self.latest_kernel_warnings),
                "successful": None,
                "resolution": "pending_diagnostics",
            }
        )
        self.pending_tactic_log_index = len(tactic_call_log) - 1

    def resolve_from_diagnostics(
        self,
        tactic_call_log: list[dict[str, Any]],
        *,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        self.latest_kernel_errors = list(errors)
        self.latest_kernel_warnings = list(warnings)

        if self.pending_tactic_log_index is None:
            return

        attempt = tactic_call_log[self.pending_tactic_log_index]
        attempt["post_diagnostic_errors"] = list(errors)
        attempt["post_diagnostic_warnings"] = list(warnings)
        attempt["successful"] = not errors
        attempt["resolution"] = "diagnostics_clean" if not errors else "diagnostics_error"
        self.pending_tactic_log_index = None

    def finalize_pending_attempt(self, tactic_call_log: list[dict[str, Any]]) -> None:
        if self.pending_tactic_log_index is None:
            return
        attempt = tactic_call_log[self.pending_tactic_log_index]
        if attempt.get("successful") is None:
            attempt["successful"] = False
            attempt["resolution"] = "unresolved_when_run_ended"
        self.pending_tactic_log_index = None

    def _next_sequence_id(self) -> int:
        self.sequence_id += 1
        return self.sequence_id


def _preview_tactic(tactic: str, limit: int = 120) -> str:
    """Collapse a tactic block to a short one-line preview for tool responses."""
    collapsed = " ".join(line.strip() for line in tactic.splitlines() if line.strip())
    if not collapsed:
        return "<empty tactic>"
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit]}..."


def _empty_tool_result_message(tool_name: str) -> str:
    """Return a non-empty fallback message for tools that yielded no text."""
    return (
        f"WARNING: Tool `{tool_name}` returned an empty result. "
        f"Use lean_diagnostic_messages on the working file before continuing."
    )


def _unavailable_tool_message(tool_name: str) -> str:
    """Return a warning result when the model asks for an unregistered tool."""
    return (
        f"ERROR: Tool `{tool_name}` is not registered in this run context. "
        "Use one of the listed tools and call lean_diagnostic_messages "
        "to inspect the current proof state."
    )


def _truncate_text(value: Any, limit: int = 500) -> str:
    """Convert arbitrary tool payloads into bounded log text."""
    text = str(value).strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _normalize_tool_arguments(arguments: Any) -> dict[str, Any] | list[Any] | str:
    """Normalize tool-call arguments for JSONL logging."""
    if isinstance(arguments, (dict, list)):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
        if isinstance(parsed, (dict, list)):
            return parsed
        return arguments
    return str(arguments)


def _extract_json_like_payload(value: Any) -> dict[str, Any] | None:
    """Best-effort parse of MCP result payloads that embed JSON as text."""
    payload = value
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            return None

    if isinstance(payload, dict):
        return payload

    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            text = first.get("text")
            if isinstance(text, str):
                try:
                    nested = json.loads(text)
                except json.JSONDecodeError:
                    return None
                if isinstance(nested, dict):
                    return nested
    return None


def _parse_diagnostic_payload(result_text: Any) -> dict[str, Any] | None:
    """Extract Lean kernel diagnostics from an MCP tool result."""
    payload = _extract_json_like_payload(result_text)
    if not isinstance(payload, dict):
        return None

    items = payload.get("items", [])
    if not isinstance(items, list):
        items = []

    errors: list[str] = []
    warnings: list[str] = []
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message", "")).strip()
        line = item.get("line")
        prefix = f"line {line}: " if line else ""
        normalized = {
            "severity": item.get("severity"),
            "message": message,
            "line": line,
            "column": item.get("column"),
        }
        normalized_items.append(normalized)
        if item.get("severity") == "error":
            errors.append(prefix + message)
        elif item.get("severity") == "warning":
            warnings.append(prefix + message)

    return {
        "success": bool(payload.get("success", False)),
        "errors": errors,
        "warnings": warnings,
        "items": normalized_items,
    }


def _status_code_from_exception(exc: Exception) -> int | None:
    """Extract an HTTP status code from Mistral SDK errors or fallback text."""
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    match = re.search(r"\bStatus (\d{3})\b", str(exc))
    if match:
        return int(match.group(1))
    return None


def _is_retryable_run_error(exc: Exception) -> bool:
    """Return True for transient Mistral API failures that deserve backoff."""
    return _status_code_from_exception(exc) in RETRYABLE_STATUS_CODES


def _is_code_3001_error(exc: Exception) -> bool:
    """Detect the malformed empty-input/tool-confirmation Conversations error."""
    text = str(exc)
    return 'code":3001' in text or "Either inputs or tool_confirmations must be provided." in text


async def _run_conversation_with_backoff(
    client,
    run_ctx,
    *,
    inputs: str,
    instructions: str,
    completion_args,
    timeout_ms: int,
    on_log: callable | None = None,
):
    """
    Run the Conversations API loop with exponential backoff on transient 429/503 failures.

    Performs one initial attempt plus four retries with delays 2s, 4s, 8s, and 16s
    around each Conversations start/append request.
    """
    from mistralai.client.beta import Beta
    from mistralai.extra.run.context import _validate_run
    from mistralai.extra.run.tools import get_function_calls

    async def request_with_backoff(request_factory, request_label: str):
        total_attempts = len(BACKOFF_DELAYS_SECONDS) + 1
        last_exc: Exception | None = None

        for attempt in range(1, total_attempts + 1):
            try:
                return await request_factory()
            except Exception as exc:
                last_exc = exc
                if not _is_retryable_run_error(exc) or attempt == total_attempts:
                    raise

                delay = BACKOFF_DELAYS_SECONDS[attempt - 1]
                status_code = _status_code_from_exception(exc)
                _log(
                    on_log,
                    "agentic_backoff",
                    (
                        f"Retryable Mistral API error ({status_code}) during "
                        f"conversation {request_label} "
                        f"attempt {attempt}/{total_attempts}; retrying in {delay}s"
                    ),
                    data=str(exc),
                    status="running",
                )
                await asyncio.sleep(delay)

        assert last_exc is not None
        raise last_exc

    req, run_result, input_entries = await _validate_run(
        beta_client=Beta(client.sdk_configuration),
        run_ctx=run_ctx,
        inputs=inputs,
        instructions=instructions,
        completion_args=completion_args,
    )

    while True:
        if run_ctx.conversation_id is None:
            res = await request_with_backoff(
                lambda: client.beta.conversations.start_async(
                    inputs=input_entries,
                    timeout_ms=timeout_ms,
                    **req,
                ),
                "start",
            )
            run_result.conversation_id = res.conversation_id
            run_ctx.conversation_id = res.conversation_id
        else:
            res = await request_with_backoff(
                lambda: client.beta.conversations.append_async(
                    conversation_id=run_ctx.conversation_id,
                    inputs=input_entries,
                    timeout_ms=timeout_ms,
                ),
                "append",
            )

        run_ctx.request_count += 1
        run_result.output_entries.extend(res.outputs)
        function_calls = get_function_calls(res.outputs)
        if not function_calls:
            break

        function_results = await run_ctx.execute_function_calls(function_calls)
        if not function_results:
            raise RuntimeError(
                "Empty tool-result cycle detected; no function results were produced."
            )

        run_result.output_entries.extend(function_results)
        input_entries = cast(list, function_results)

    return run_result


def _sanitize_tool_result_text(tool_name: str, result_text: Any) -> str:
    """Normalize a tool result to a non-empty string payload for Mistral."""
    if isinstance(result_text, str) and result_text.strip():
        return result_text
    return _empty_tool_result_message(tool_name)


def _build_interrupted_run_result(
    *,
    controller: ProofFileController,
    model_text: str,
    tool_trace_entries: list[dict[str, Any]],
    tactic_call_log: list[dict[str, Any]],
    steps_used: int,
    start_time: float,
    interruption_message: str,
    stop_reason: str,
    agent_summary: str,
    partial: bool,
) -> dict[str, Any]:
    """Build a graceful partial result after a timeout or external API interruption."""
    current_tactics = controller.current_tactic_block
    current_code = controller.current_lean_code
    partial_verification = None

    if current_tactics != "sorry":
        try:
            partial_verification = verify(current_code)
        except Exception:
            partial_verification = None

    elapsed = time.time() - start_time
    success = bool(partial_verification and partial_verification["success"])
    final_stop_reason = STOP_PROOF_COMPLETE if success else stop_reason

    if partial_verification:
        errors = list(partial_verification.get("errors", []))
        warnings = list(partial_verification.get("warnings", []))
        if interruption_message not in errors and interruption_message not in warnings:
            warnings.append(interruption_message)
        output_lean = partial_verification.get("output_lean")
    else:
        errors = [interruption_message]
        warnings = []
        output_lean = None

    return {
        "success": success,
        "strategy": model_text,
        "proof_tactics": current_tactics,
        "full_lean_code": current_code,
        "errors": errors,
        "warnings": warnings,
        "tool_trace": tool_trace_entries,
        "tactic_calls": tactic_call_log,
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "steps_used": steps_used,
        "mcp_enabled": True,
        "agent_summary": agent_summary,
        "stop_reason": final_stop_reason,
        "output_lean": output_lean,
        "elapsed_seconds": elapsed,
        "partial": partial,
    }


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

## Discovering tactics with code actions

When you need the optimal tactic or want to resolve a "Try this:" suggestion:
1. Apply a discovery tactic via apply_tactic: simp?, exact?, or apply?
2. Call lean_code_actions on {file_path} at that line number
3. Read the resolved tactic from the returned edit suggestion
4. Call apply_tactic with the resolved tactic

Use lean_code_actions when:
- You've tried 2+ tactics that failed
- lean_diagnostic_messages shows "Try this:" suggestions
- You want to replace simp with its minimal simp only [...] form

## Rules

- Do NOT use sorry.
- Keep tactic blocks concise.
- If you cannot find a proof after a few attempts, say so and stop.
- STOP as soon as lean_diagnostic_messages shows no errors and no sorry warnings.
"""


def _build_instructions(file_path: str, goal_line: int) -> str:
    """Inject runtime paths into the agent prompt without using format()."""
    return AGENTIC_INSTRUCTIONS_TEMPLATE.replace("{file_path}", file_path).replace(
        "{goal_line}", str(goal_line)
    )


# ---------------------------------------------------------------------------
# Tool function factory
# ---------------------------------------------------------------------------


def _make_apply_tactic(controller: ProofFileController, trace_recorder: TraceRecorder):
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
        trace_recorder.note_tactic_attempt(tactic_call_log, tactic)

        try:
            controller.replace_tactic_block(tactic)
        except ValueError as exc:
            return f"ERROR: Invalid tactic block — {exc}"

        tactic_preview = _preview_tactic(tactic)
        response = (
            f"OK: Tactic written to {controller.mcp_file_path}. "
            f"Preview: {tactic_preview}. "
            "Next step: use lean_diagnostic_messages on "
            f"{controller.mcp_file_path} to check for errors before applying "
            "more tactics."
        )
        return response if response.strip() else _empty_tool_result_message("apply_tactic")

    return apply_tactic, tactic_call_log


def _install_guarded_execute_function_calls(
    run_ctx,
    tracker: AgenticToolTracker,
    trace_recorder: TraceRecorder,
    tactic_call_log: list[dict[str, Any]],
):
    """
    Wrap RunContext.execute_function_calls so tool execution stays well-formed.

    This guard does three things:
    1. Prevents unknown tool calls from collapsing into `inputs=[]` on the next append.
    2. Enforces the apply_tactic circuit breaker after five unchecked writes.
    3. Guarantees that every function result fed back to Mistral is non-empty text.
    """
    from mistralai.client.models.functionresultentry import FunctionResultEntry
    from mistralai.extra.run.tools import create_function_result

    async def guarded_execute_function_calls(function_calls):
        results: list[FunctionResultEntry] = []

        for function_call in function_calls:
            tool_name = function_call.name
            run_tool = run_ctx._callable_tools.get(tool_name)
            tool_kind = "local" if tool_name == "apply_tactic" else "mcp"
            request_index = getattr(run_ctx, "request_count", 0) + 1
            arguments = getattr(function_call, "arguments", {})

            if run_tool is None:
                unavailable_result = _unavailable_tool_message(tool_name)
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=unavailable_result,
                    )
                )
                trace_recorder.append_tool_call(
                    request_index=request_index,
                    tool_call_id=function_call.tool_call_id,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    arguments=arguments,
                    result_text=unavailable_result,
                    status="unavailable",
                )
                continue

            if tool_name == "apply_tactic" and tracker.should_block_apply():
                tracker.note_circuit_breaker()
                blocked_result = CIRCUIT_BREAKER_WARNING
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=blocked_result,
                    )
                )
                trace_recorder.append_tool_call(
                    request_index=request_index,
                    tool_call_id=function_call.tool_call_id,
                    tool_name=tool_name,
                    tool_kind=tool_kind,
                    arguments=arguments,
                    result_text=blocked_result,
                    status="blocked",
                    blocked=True,
                )
                continue

            status = "ok"
            try:
                function_result = await create_function_result(
                    function_call=function_call,
                    run_tool=run_tool,
                    continue_on_fn_error=True,
                )
            except Exception as exc:  # pragma: no cover - defensive fallback over SDK helper
                status = "error"
                function_result = FunctionResultEntry(
                    tool_call_id=function_call.tool_call_id,
                    result=f"ERROR while executing {tool_name}: {exc}",
                )

            function_result.result = _sanitize_tool_result_text(
                tool_name,
                getattr(function_result, "result", ""),
            )
            results.append(function_result)

            diagnostic_payload = None
            if tool_name == "lean_diagnostic_messages":
                diagnostic_payload = _parse_diagnostic_payload(function_result.result)
                if diagnostic_payload is not None:
                    trace_recorder.resolve_from_diagnostics(
                        tactic_call_log,
                        errors=diagnostic_payload["errors"],
                        warnings=diagnostic_payload["warnings"],
                    )

            trace_recorder.append_tool_call(
                request_index=request_index,
                tool_call_id=function_call.tool_call_id,
                tool_name=tool_name,
                tool_kind=tool_kind,
                arguments=arguments,
                result_text=function_result.result,
                status=status,
                diagnostic_payload=diagnostic_payload,
            )

            if tool_name == "lean_diagnostic_messages":
                tracker.note_diagnostic_check()
            elif tool_name == "apply_tactic":
                tracker.note_apply_tactic_executed()

        if not results:
            for function_call in function_calls:
                results.append(
                    FunctionResultEntry(
                        tool_call_id=function_call.tool_call_id,
                        result=(
                            "WARNING: No executable tool results were produced. "
                            "Use lean_diagnostic_messages to inspect the "
                            "current proof state before continuing."
                        ),
                    )
                )

        return results

    run_ctx.execute_function_calls = guarded_execute_function_calls


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
    4. Final verification via the local Lean compiler
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
            on_log,
            "agentic_init",
            f"Working file: {controller.mcp_file_path}",
            data=controller.current_lean_code,
            status="done",
        )

        # --- Step 2: Set up Mistral RunContext with tools ---
        _log(on_log, "agentic_setup", "Setting up Leanstral + MCP tools...", status="running")

        trace_recorder = TraceRecorder()
        apply_tactic_fn, tactic_call_log = _make_apply_tactic(controller, trace_recorder)
        tool_tracker = AgenticToolTracker()
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
        tool_trace_entries: list[dict[str, Any]] = trace_recorder.entries

        steps_used = 0
        run_ctx = None

        try:
            async with open_mistral_run_context(model=MODEL) as run_ctx:
                run_ctx.agentic_tool_tracker = tool_tracker
                run_ctx.register_func(apply_tactic_fn)
                _install_guarded_execute_function_calls(
                    run_ctx,
                    tool_tracker,
                    trace_recorder,
                    tactic_call_log,
                )

                _log(
                    on_log,
                    "agentic_setup",
                    f"Tools registered: {len(run_ctx.get_tools())} total",
                    status="done",
                )

                result = await _run_conversation_with_backoff(
                    client,
                    run_ctx,
                    inputs=user_prompt,
                    instructions=instructions,
                    completion_args=CompletionArgs(
                        temperature=1.0,
                        max_tokens=32000,
                    ),
                    timeout_ms=TIMEOUT_MS,
                    on_log=on_log,
                )

                # Extract results
                steps_used = run_ctx.request_count

                for entry in result.output_entries:
                    if getattr(entry, "type", "") == "message.output":
                        trace_recorder.append_message_output(
                            request_index=getattr(run_ctx, "request_count", steps_used),
                            content=getattr(entry, "content", ""),
                        )

                try:
                    model_text = result.output_as_text
                except (ValueError, AttributeError):
                    model_text = ""

        except asyncio.TimeoutError:
            steps_used = getattr(run_ctx, "request_count", steps_used)
            error_message = f"run_async timed out after {TIMEOUT_MS}ms"
            trace_recorder.finalize_pending_attempt(tactic_call_log)
            return _build_interrupted_run_result(
                controller=controller,
                model_text=model_text,
                tool_trace_entries=tool_trace_entries,
                tactic_call_log=tactic_call_log,
                steps_used=steps_used,
                start_time=start_time,
                interruption_message=error_message,
                stop_reason=STOP_TIMEOUT,
                agent_summary=(
                    "Leanstral agentic prover timed out before finishing the proving loop. "
                    "Returning the latest proof state for inspection."
                ),
                partial=True,
            )
        except Exception as exc:
            _log(on_log, "agentic_run", f"run_async error: {exc}", status="error")
            steps_used = getattr(run_ctx, "request_count", steps_used)

            if _is_retryable_run_error(exc):
                interruption_message = (
                    "Agentic run halted after exhausting retry backoff for a "
                    "transient Mistral API error."
                )
                trace_recorder.finalize_pending_attempt(tactic_call_log)
                return _build_interrupted_run_result(
                    controller=controller,
                    model_text=model_text,
                    tool_trace_entries=tool_trace_entries,
                    tactic_call_log=tactic_call_log,
                    steps_used=steps_used,
                    start_time=start_time,
                    interruption_message=interruption_message,
                    stop_reason=STOP_PROOF_INCOMPLETE,
                    agent_summary=(
                        "Leanstral agentic prover exhausted exponential backoff retries "
                        "for a transient API error and returned the latest proof state."
                    ),
                    partial=True,
                )

            if _is_code_3001_error(exc):
                interruption_message = (
                    "Agentic run halted after an empty tool-result cycle. "
                    "The current proof state was preserved so Leanstral can "
                    "resume from diagnostics."
                )
                trace_recorder.finalize_pending_attempt(tactic_call_log)
                return _build_interrupted_run_result(
                    controller=controller,
                    model_text=model_text,
                    tool_trace_entries=tool_trace_entries,
                    tactic_call_log=tactic_call_log,
                    steps_used=steps_used,
                    start_time=start_time,
                    interruption_message=interruption_message,
                    stop_reason=STOP_PROOF_INCOMPLETE,
                    agent_summary=(
                        "Leanstral agentic prover intercepted an empty tool-result cycle "
                        "and returned the latest proof state instead of "
                        "surfacing a raw API 3001 failure."
                    ),
                    partial=True,
                )

            stop_reason = STOP_RUN_ERROR
            elapsed = time.time() - start_time
            trace_recorder.finalize_pending_attempt(tactic_call_log)
            return {
                "success": False,
                "strategy": model_text,
                "proof_tactics": controller.current_tactic_block,
                "full_lean_code": controller.current_lean_code,
                "errors": [str(exc)],
                "warnings": [],
                "tool_trace": tool_trace_entries,
                "tactic_calls": tactic_call_log,
                "trace_schema_version": TRACE_SCHEMA_VERSION,
                "steps_used": steps_used,
                "mcp_enabled": True,
                "agent_summary": f"run_async failed: {exc}",
                "stop_reason": stop_reason,
                "output_lean": None,
                "elapsed_seconds": elapsed,
                "partial": False,
            }

        _log(
            on_log,
            "agentic_run",
            "Leanstral loop completed "
            f"({steps_used} API round-trips, {len(tactic_call_log)} tactic calls)",
            status="done",
        )
        trace_recorder.finalize_pending_attempt(tactic_call_log)

        # --- Step 4: Check if proof looks complete (pre-verification) ---
        current_tactics = controller.current_tactic_block
        if "sorry" in current_tactics:
            stop_reason = STOP_PROOF_INCOMPLETE
            _log(on_log, "agentic_check", "Proof still contains sorry", status="error")
        else:
            stop_reason = STOP_PROOF_COMPLETE
            _log(on_log, "agentic_check", "Proof appears complete (no sorry)", status="done")

        # --- Step 5: Final verification via the local Lean compiler ---
        _log(on_log, "agentic_verify", "Running final Lean verification...", status="running")
        verification = verify(controller.current_lean_code)

        if verification["success"]:
            stop_reason = STOP_PROOF_COMPLETE
            _log(on_log, "agentic_verify", "Verified — Lean check passed", status="done")
        else:
            if stop_reason == STOP_PROOF_COMPLETE:
                stop_reason = (
                    STOP_PROOF_INCOMPLETE  # MCP said done but final verification disagreed
                )
            error_preview = str(verification["errors"][:2])
            _log(
                on_log,
                "agentic_verify",
                f"Verification failed: {error_preview}",
                data=str(verification["errors"]),
                status="error",
            )

        elapsed = time.time() - start_time
        success = verification["success"]

        summary_parts = [
            f"Leanstral agentic prover: {steps_used} API round-trips, "
            f"{len(tactic_call_log)} tactic applications.",
        ]
        if tool_tracker.total_diagnostic_calls:
            summary_parts.append(
                f"Diagnostics checks observed: {tool_tracker.total_diagnostic_calls}."
            )
        if tool_tracker.circuit_breaker_hits:
            summary_parts.append(
                f"Circuit breaker triggered {tool_tracker.circuit_breaker_hits} time(s)."
            )
        if success:
            summary_parts.append("Proof verified by the local Lean compiler.")
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
            "trace_schema_version": TRACE_SCHEMA_VERSION,
            "steps_used": steps_used,
            "mcp_enabled": True,
            "agent_summary": " ".join(summary_parts),
            "stop_reason": stop_reason,
            "output_lean": verification.get("output_lean"),
            "axiom_info": verification.get("axiom_info"),
            "elapsed_seconds": elapsed,
            "partial": False,
        }
    finally:
        controller.cleanup()


# ---------------------------------------------------------------------------
# Backend registration
# ---------------------------------------------------------------------------


@register_prover("leanstral")
class LeanstralProver:
    """Leanstral + lean-lsp-mcp agentic prover via Mistral's Conversations API."""

    @property
    def name(self) -> str:
        return "leanstral"

    def prove(
        self,
        theorem_with_sorry: str,
        on_log: Any | None = None,
    ) -> dict[str, Any]:
        return prove_theorem_agentic(
            theorem_with_sorry=theorem_with_sorry,
            on_log=on_log,
        )


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
    to build a proof interactively. Final verification is via the local Lean compiler.

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
    print("Run tests via: pytest -m live tests/test_agentic_examples.py")
