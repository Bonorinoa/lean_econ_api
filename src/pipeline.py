"""
pipeline.py

Orchestration layer: parse → formalize → prove → verify.

Input:  raw text (LaTeX, plain English, or raw Lean 4)
Output: dict with {success, lean_code, errors, proof_strategy, ...}

Two-phase execution:
  formalize_claim()  — Phase 1: parse + LLM formalization
  prove_and_verify() — Phase 2: pass@N proof generation + lake build
  run_pipeline()     — Runs both phases in sequence (CLI / tests)
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import TypedDict

from eval_logger import log_run
from formalizer import formalize
from lean_verifier import verify
from leanstral_client import prove_theorem, prove_theorem_with_feedback

PASS_AT_N = 5  # Number of independent proof attempts before giving up


class ProveResult(TypedDict):
    """Normalized proof-generation result shared by batch and agentic paths."""

    success: bool
    lean_code: str
    errors: list[str]
    warnings: list[str]
    proof_strategy: str
    proof_tactics: str
    output_lean: str | None
    proof_generated: bool
    attempts_used: int
    prover_mode: str


def _log(on_log, stage: str, message: str, data: str | None = None, status: str = "done"):
    """
    Emit a pipeline log entry.

    If on_log is provided (Streamlit callback), calls it with a structured dict.
    Otherwise falls back to print() so terminal usage is unaffected.
    """
    if on_log:
        on_log({"stage": stage, "message": message, "data": data, "status": status})
    else:
        print(f"[pipeline] {stage}: {message}")


# ---------------------------------------------------------------------------
# Step 1: Parse raw input
# ---------------------------------------------------------------------------

def parse_claim(raw_input: str) -> dict:
    """
    Strip LaTeX boilerplate from raw input and return cleaned text.

    Args:
        raw_input: Raw user input — could be a full .tex file excerpt or plain text.

    Returns:
        dict with key:
          - text (str): Cleaned claim text ready for formalization.
    """
    text = raw_input.strip()
    text = re.sub(r"\\begin\{(claim|theorem|proposition|lemma)\}", "", text)
    text = re.sub(r"\\end\{(claim|theorem|proposition|lemma)\}", "", text)
    text = re.sub(r"^%.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {"text": text}


# ---------------------------------------------------------------------------
# Step 2: Formalize (Phase 1)
# ---------------------------------------------------------------------------

def formalize_claim(raw_input: str, on_log: callable | None = None) -> dict:
    """
    Phase 1: parse + formalize only. Returns the theorem statement for user review.

    Auto-detects raw Lean input and skips formalization if detected.

    Returns:
        Output of formalizer.formalize() with keys:
          success, theorem_code, attempts, errors, formalization_failed, failure_reason
    """
    # Auto-detect raw Lean — skip formalization
    if "import Mathlib" in raw_input or (":= by" in raw_input and "sorry" in raw_input):
        _log(on_log, "parse", "Raw Lean input detected — skipping formalization", status="done")
        return {
            "success": True,
            "theorem_code": raw_input.strip(),
            "attempts": 0,
            "errors": [],
            "formalization_failed": False,
            "failure_reason": None,
        }

    _log(on_log, "parse", "Cleaning input...", status="running")
    parsed = parse_claim(raw_input)
    _log(on_log, "parse", "Input cleaned", status="done")

    _log(on_log, "formalize", "Calling Leanstral to formalize claim...", status="running")
    result = formalize(parsed["text"], on_log=on_log)

    if result["formalization_failed"]:
        _log(on_log, "formalize", f"Formalization failed: {result['failure_reason']}", status="error")
    elif result["success"]:
        _log(on_log, "formalize",
             f"Formalized in {result['attempts']} attempt(s)",
             data=result["theorem_code"],
             status="done")
    else:
        _log(on_log, "formalize",
             f"Sorry-validation failed after {result['attempts']} attempt(s)",
             data="\n".join(result["errors"][:2]),
             status="error")

    return result


# ---------------------------------------------------------------------------
# Step 3: Prove & Verify (Phase 2)
# ---------------------------------------------------------------------------

def prove_and_verify(
    theorem_with_sorry: str,
    on_log: callable | None = None,
    prover_mode: str = "batch",
) -> ProveResult:
    """
    Phase 2: proof generation + verification.

    Args:
        theorem_with_sorry: Lean 4 theorem with sorry placeholder.
        on_log: Optional callback for pipeline log entries.
        prover_mode: "batch" (default, pass@N) or "agentic" (Leanstral+MCP).

    Returns:
        dict with keys:
          - success (bool)
          - lean_code (str): Final .lean file (verified or last attempted)
          - errors (list[str])
          - warnings (list[str])
          - proof_strategy (str)
          - proof_tactics (str)
          - output_lean (str | None)
          - proof_generated (bool): True if at least one proof attempt ran
          - attempts_used (int)
          - prover_mode (str): Which prover was used
    """
    if prover_mode == "agentic":
        return _prove_and_verify_agentic(theorem_with_sorry, on_log=on_log)
    proof_result = None
    verification = None
    attempts_used = 0
    previous_proof = None
    previous_error = None

    for attempt in range(1, PASS_AT_N + 1):
        attempts_used = attempt
        _log(on_log, f"attempt_{attempt}",
             f"Attempt {attempt}/{PASS_AT_N} — generating proof...",
             status="running")

        # Use feedback on attempts 2+ if we have context from a prior failure
        if attempt > 1 and previous_proof and previous_error:
            proof_result = prove_theorem_with_feedback(
                theorem_with_sorry, previous_error, previous_proof
            )
        else:
            proof_result = prove_theorem(theorem_with_sorry)

        _log(on_log, f"attempt_{attempt}",
             f"Attempt {attempt}/{PASS_AT_N} — strategy received",
             data=proof_result["strategy"],
             status="done")

        _log(on_log, f"verify_{attempt}",
             f"Attempt {attempt}/{PASS_AT_N} — verifying with lake build...",
             status="running")
        verification = verify(proof_result["full_lean_code"])

        if verification["success"]:
            _log(on_log, f"verify_{attempt}", f"Attempt {attempt} PASSED", status="done")
            break

        # "No goals" recovery — strip last tactic, re-verify without a new API call
        if _is_no_goals_error(verification):
            _log(on_log, f"verify_{attempt}",
                 "Stripping redundant tactic (no goals recovery)...",
                 status="running")
            trimmed_code = _drop_redundant_tactic(
                proof_result["full_lean_code"],
                verification,
            )
            if trimmed_code != proof_result["full_lean_code"]:
                verification = verify(trimmed_code)
                proof_result = {**proof_result, "full_lean_code": trimmed_code}
                if verification["success"]:
                    _log(on_log, f"verify_{attempt}",
                         f"Attempt {attempt} PASSED after tactic strip",
                         status="done")
                    break
                _log(on_log, f"verify_{attempt}",
                     f"Attempt {attempt} still failed after strip",
                     data=str(verification["errors"][:2]),
                     status="error")

        _log(on_log, f"verify_{attempt}",
             f"Attempt {attempt} failed",
             data=str(verification["errors"][:2]),
             status="error")

        # Capture feedback for next attempt
        previous_proof = proof_result["proof_tactics"]
        previous_error = _build_error_context(verification)

    assert proof_result is not None
    assert verification is not None

    return {
        "success": verification["success"],
        "lean_code": proof_result["full_lean_code"],
        "errors": verification["errors"],
        "warnings": verification["warnings"],
        "proof_strategy": proof_result["strategy"],
        "proof_tactics": proof_result["proof_tactics"],
        "output_lean": verification.get("output_lean"),
        "proof_generated": True,
        "attempts_used": attempts_used,
        "prover_mode": "batch",
    }


def _prove_and_verify_agentic(
    theorem_with_sorry: str,
    on_log: callable | None = None,
) -> ProveResult:
    """Dispatch to the agentic prover and normalize its result to the batch shape."""
    from agentic_prover import prove_theorem_agentic

    _log(on_log, "agentic_dispatch", "Using agentic prover (Leanstral+MCP)...", status="running")
    result = prove_theorem_agentic(theorem_with_sorry, on_log=on_log)
    _log(on_log, "agentic_dispatch",
         f"Agentic prover finished: {'PASS' if result['success'] else 'FAIL'}",
         status="done" if result["success"] else "error")

    return {
        "success": result["success"],
        "lean_code": result["full_lean_code"],
        "errors": result["errors"],
        "warnings": result.get("warnings", []),
        "proof_strategy": result.get("strategy", ""),
        "proof_tactics": result["proof_tactics"],
        "output_lean": result.get("output_lean"),
        "proof_generated": True,
        "attempts_used": result.get("steps_used", 0),
        "prover_mode": "agentic",
    }


# ---------------------------------------------------------------------------
# Step 4: Full pipeline (CLI / tests)
# ---------------------------------------------------------------------------

def run_pipeline(
    raw_input: str,
    on_log: callable | None = None,
    preformalized_theorem: str | None = None,
    prover_mode: str = "batch",
) -> dict:
    """
    Full pipeline: parse → formalize → prove → verify.

    If preformalized_theorem is provided, skip parse and formalize.
    If raw_input looks like raw Lean, skip formalization automatically.

    Returns dict with all keys needed by app.py:
      success, lean_code, errors, warnings, proof_strategy, proof_tactics,
      theorem_statement, formalization_attempts, formalization_failed,
      failure_reason, output_lean, phase
    """
    start = time.time()

    # --- Phase 1: Formalize ---
    if preformalized_theorem is not None:
        f_result = {
            "success": True,
            "theorem_code": preformalized_theorem.strip(),
            "attempts": 0,
            "errors": [],
            "formalization_failed": False,
            "failure_reason": None,
        }
    else:
        f_result = formalize_claim(raw_input, on_log=on_log)

    if not f_result["success"]:
        return {
            "success": False,
            "lean_code": f_result.get("theorem_code", ""),
            "errors": f_result.get("errors", []),
            "warnings": [],
            "proof_strategy": "",
            "proof_tactics": "",
            "theorem_statement": f_result.get("theorem_code", ""),
            "formalization_attempts": f_result.get("attempts", 0),
            "formalization_failed": f_result.get("formalization_failed", False),
            "failure_reason": f_result.get("failure_reason"),
            "output_lean": None,
            "proof_generated": False,
            "phase": "failed",
            "elapsed_seconds": time.time() - start,
        }

    theorem_with_sorry = f_result["theorem_code"]

    # --- Phase 2: Prove & Verify ---
    pv_result = prove_and_verify(theorem_with_sorry, on_log=on_log, prover_mode=prover_mode)

    if pv_result["success"]:
        phase = "verified"
    elif pv_result["proof_generated"]:
        phase = "proved"  # proof was generated but Lean rejected it
    else:
        phase = "failed"

    result = {
        "success": pv_result["success"],
        "lean_code": pv_result["lean_code"],
        "errors": pv_result["errors"],
        "warnings": pv_result["warnings"],
        "proof_strategy": pv_result["proof_strategy"],
        "proof_tactics": pv_result["proof_tactics"],
        "theorem_statement": theorem_with_sorry,
        "formalization_attempts": f_result["attempts"],
        "formalization_failed": False,
        "failure_reason": None,
        "output_lean": pv_result["output_lean"],
        "proof_generated": pv_result["proof_generated"],
        "phase": phase,
        "elapsed_seconds": time.time() - start,
    }

    log_run({
        "input_text": raw_input[:500] if preformalized_theorem is None else "",
        "input_mode": "raw_lean" if f_result["attempts"] == 0 else "latex_or_text",
        "formalization": {
            "success": f_result["success"],
            "attempts": f_result["attempts"],
            "theorem_code": f_result["theorem_code"],
            "errors": f_result["errors"],
            "model": "labs-leanstral-2603",
            "formalization_failed": f_result["formalization_failed"],
            "failure_reason": f_result["failure_reason"],
        },
        "proving": {
            "success": pv_result["success"],
            "attempts_used": pv_result["attempts_used"],
            "proof_strategy": pv_result["proof_strategy"],
            "proof_tactics": pv_result["proof_tactics"],
        },
        "verification": {
            "success": pv_result["success"],
            "errors": pv_result["errors"],
            "warnings": pv_result["warnings"],
        },
        "elapsed_seconds": result["elapsed_seconds"],
    })

    return result


# --- Helpers ---

def _build_error_context(verification: dict) -> str:
    """
    Build a concise error context string from a failed verification result.

    Includes Lean error messages and stdout (which may contain unsolved goals).
    Bounded to avoid prompt bloat.
    """
    parts = []
    errors = verification.get("errors", [])
    if errors:
        parts.append("Errors:\n" + "\n".join(errors[:5]))
    stdout = verification.get("stdout", "")
    if stdout.strip():
        trimmed = stdout[:1500]
        if len(stdout) > 1500:
            trimmed += "\n... (truncated)"
        parts.append("Build output:\n" + trimmed)
    elif not errors:
        stderr = verification.get("stderr", "")
        if stderr.strip():
            trimmed = stderr[:1000]
            if len(stderr) > 1000:
                trimmed += "\n... (truncated)"
            parts.append("Build stderr:\n" + trimmed)
    return "\n\n".join(parts) if parts else "Unknown error"


def _is_no_goals_error(verification: dict) -> bool:
    """Return True if any Lean error mentions 'No goals to be solved'."""
    combined = (
        "\n".join(verification.get("errors", []))
        + verification.get("stdout", "")
        + verification.get("stderr", "")
    )
    return "No goals to be solved" in combined or "no goals" in combined.lower()


def _drop_redundant_tactic(lean_code: str, verification: dict) -> str:
    """
    Remove the tactic line Lean flagged as redundant, falling back to the last line.

    Lean often reports "No goals to be solved" with an exact line number.
    When present, remove that line so we do not accidentally delete a later,
    still-necessary tactic in another proof branch.
    """
    lines = lean_code.splitlines()
    for error in verification.get("errors", []):
        if "No goals to be solved" not in error:
            continue
        match = re.search(r":(\d+):\d+:", error)
        if match:
            line_index = int(match.group(1)) - 1
            if 0 <= line_index < len(lines) and lines[line_index].strip():
                del lines[line_index]
                return "\n".join(lines) + "\n"

    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            del lines[i]
            return "\n".join(lines) + "\n"
    return lean_code


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raw = Path(sys.argv[1]).read_text()
        result = run_pipeline(raw)
        print(f"\nResult: {'PASS' if result['success'] else 'FAIL'}")
        print(f"Phase:  {result['phase']}")
        print(f"Lean code:\n{result['lean_code']}")
        if result["errors"]:
            print(f"Errors: {result['errors']}")
    else:
        print("Usage: python src/pipeline.py <claim_file.tex>")
        print("Run tests via: python tests/test_pipeline_smoke.py")
