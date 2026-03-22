"""
pipeline.py

Orchestration layer: parse → formalize → prove → verify.

Input:  raw text (LaTeX, plain English, or raw Lean 4)
Output: dict with {success, lean_code, errors, proof_strategy, ...}
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import Any, TypedDict

from eval_logger import log_run
from formalizer import formalize
from prover_backend import get_prover
from result_cache import result_cache


class ProveResult(TypedDict):
    """Normalized output from the proving stage."""

    success: bool
    lean_code: str
    errors: list[str]
    warnings: list[str]
    proof_strategy: str
    proof_tactics: str
    output_lean: str | None
    proof_generated: bool
    attempts_used: int
    partial: bool
    stop_reason: str | None
    tool_trace: list[dict[str, Any]]
    tactic_calls: list[dict[str, Any]]
    trace_schema_version: int
    agent_summary: str
    agent_elapsed_seconds: float
    axiom_info: dict[str, Any] | None


def _build_run_log_entry(
    *,
    raw_input: str,
    input_text: str,
    input_mode: str,
    formalization: dict[str, Any],
    proving: dict[str, Any],
    verification: dict[str, Any],
    elapsed_seconds: float,
    from_cache: bool,
    partial: bool,
    stop_reason: str | None,
    cache_replay: bool = False,
) -> dict[str, Any]:
    """Build the append-only eval-log payload for both fresh runs and cache replays."""
    entry = {
        "original_raw_claim": raw_input,
        "input_text": input_text,
        "input_mode": input_mode,
        "formalization": formalization,
        "proving": proving,
        "verification": verification,
        "elapsed_seconds": elapsed_seconds,
        "from_cache": from_cache,
        "partial": partial,
        "stop_reason": stop_reason,
    }
    if cache_replay:
        entry["cache_replay"] = True
    return entry


def _log(
    on_log,
    stage: str,
    message: str,
    data: str | None = None,
    status: str = "done",
    elapsed_ms: float | None = None,
):
    """Emit a pipeline log entry."""
    if on_log:
        on_log({"stage": stage, "message": message, "data": data,
                "status": status, "elapsed_ms": elapsed_ms})
    else:
        print(f"[pipeline] {stage}: {message}")


def parse_claim(raw_input: str) -> dict:
    """Strip LaTeX boilerplate from raw input and return cleaned text."""
    text = raw_input.strip()
    text = re.sub(r"\\begin\{(claim|theorem|proposition|lemma)\}", "", text)
    text = re.sub(r"\\end\{(claim|theorem|proposition|lemma)\}", "", text)
    text = re.sub(r"^%.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return {"text": text}


def formalize_claim(
    raw_input: str,
    on_log: callable | None = None,
    preamble_names: list[str] | None = None,
) -> dict:
    """
    Phase 1: parse + formalize only. Returns the theorem statement for user review.

    Auto-detects raw Lean input and skips formalization if detected.
    """
    if "import Mathlib" in raw_input or (":= by" in raw_input and "sorry" in raw_input):
        _log(on_log, "parse", "Raw Lean input detected — skipping formalization", status="done")
        return {
            "success": True,
            "theorem_code": raw_input.strip(),
            "attempts": 0,
            "errors": [],
            "formalization_failed": False,
            "failure_reason": None,
            "preamble_used": [],
            "diagnosis": None,
            "suggested_fix": None,
            "fixable": None,
        }

    _log(on_log, "parse", "Cleaning input...", status="running")
    t_parse = time.time()
    parsed = parse_claim(raw_input)
    _log(on_log, "parse", "Input cleaned", status="done", elapsed_ms=(time.time() - t_parse) * 1000)

    _log(on_log, "formalize", "Calling Leanstral to formalize claim...", status="running")
    t_formalize = time.time()
    result = formalize(parsed["text"], on_log=on_log, preamble_names=preamble_names)
    formalize_elapsed_ms = (time.time() - t_formalize) * 1000

    if result["formalization_failed"]:
        _log(
            on_log, "formalize", f"Formalization failed: {result['failure_reason']}",
            status="error", elapsed_ms=formalize_elapsed_ms,
        )
    elif result["success"]:
        _log(
            on_log,
            "formalize",
            f"Formalized in {result['attempts']} attempt(s)",
            data=result["theorem_code"],
            status="done",
            elapsed_ms=formalize_elapsed_ms,
        )
    else:
        _log(
            on_log,
            "formalize",
            f"Sorry-validation failed after {result['attempts']} attempt(s)",
            data="\n".join(result["errors"][:2]),
            status="error",
            elapsed_ms=formalize_elapsed_ms,
        )

    return result


def prove_and_verify(
    theorem_with_sorry: str,
    on_log: callable | None = None,
    prover_name: str = "leanstral",
) -> ProveResult:
    """Phase 2: proof generation plus final Lean verification."""
    prover = get_prover(prover_name)
    success = False
    _log(on_log, "prover_dispatch", f"Using prover: {prover.name}", status="running")
    t_prover = time.time()
    result = prover.prove(theorem_with_sorry, on_log=on_log)
    success = result.get("success", False)
    _log(
        on_log,
        "prover_dispatch",
        f"Prover finished: {'PASS' if success else 'FAIL'}",
        status="done" if success else "error",
        elapsed_ms=(time.time() - t_prover) * 1000,
    )

    return {
        "success": success,
        "lean_code": result.get("full_lean_code", ""),
        "errors": result.get("errors", []),
        "warnings": result.get("warnings", []),
        "proof_strategy": result.get("strategy", ""),
        "proof_tactics": result.get("proof_tactics", ""),
        "output_lean": result.get("output_lean"),
        "proof_generated": result.get("proof_generated", True),
        "attempts_used": result.get("steps_used", 0),
        "partial": result.get("partial", False),
        "stop_reason": result.get("stop_reason"),
        "tool_trace": result.get("tool_trace", []),
        "tactic_calls": result.get("tactic_calls", []),
        "trace_schema_version": result.get("trace_schema_version", 1),
        "agent_summary": result.get("agent_summary", ""),
        "agent_elapsed_seconds": result.get("elapsed_seconds", 0.0),
        "axiom_info": result.get("axiom_info"),
    }


def run_pipeline(
    raw_input: str,
    on_log: callable | None = None,
    preformalized_theorem: str | None = None,
    use_cache: bool = True,
) -> dict:
    """
    Full pipeline: parse → formalize → prove → verify.

    If preformalized_theorem is provided, skip parse and formalize.
    If raw_input looks like raw Lean, skip formalization automatically.
    """
    start = time.time()
    cache_key_input = preformalized_theorem or raw_input

    if use_cache:
        cached = result_cache.get(cache_key_input)
        if cached is not None:
            _log(on_log, "cache", "Cache hit — returning verified result",
                 status="done", elapsed_ms=0.0)
            cached["elapsed_seconds"] = 0.0
            cached["from_cache"] = True
            cached.setdefault("partial", False)
            cached.setdefault("stop_reason", None)
            cached.setdefault("tool_trace", [])
            cached.setdefault("tactic_calls", [])
            cached.setdefault("trace_schema_version", 1)
            cached.setdefault("agent_summary", "")
            cached.setdefault("agent_elapsed_seconds", 0.0)
            cached_theorem = (
                cached.get("theorem_statement")
                or cached.get("lean_code")
                or cache_key_input
            )
            log_run(
                _build_run_log_entry(
                    raw_input=raw_input,
                    input_text="",
                    input_mode="cache",
                    formalization={
                        "success": True,
                        "attempts": cached.get("formalization_attempts", 0),
                        "theorem_code": str(cached_theorem),
                        "errors": [],
                        "model": "cache_replay",
                        "formalization_failed": False,
                        "failure_reason": None,
                    },
                    proving={
                        "success": cached.get("success", True),
                        "attempts_used": cached.get("attempts_used", 0),
                        "proof_strategy": cached.get("proof_strategy", ""),
                        "proof_tactics": cached.get("proof_tactics", ""),
                        "tool_trace": cached.get("tool_trace", []),
                        "tactic_calls": cached.get("tactic_calls", []),
                        "trace_schema_version": cached.get("trace_schema_version", 1),
                        "agent_summary": cached.get("agent_summary", ""),
                    },
                    verification={
                        "success": cached.get("success", True),
                        "errors": cached.get("errors", []),
                        "warnings": cached.get("warnings", []),
                    },
                    elapsed_seconds=0.0,
                    from_cache=True,
                    partial=cached.get("partial", False),
                    stop_reason="cache_hit",
                    cache_replay=True,
                )
            )
            return cached

    if preformalized_theorem is not None:
        f_result = {
            "success": True,
            "theorem_code": preformalized_theorem.strip(),
            "attempts": 0,
            "errors": [],
            "formalization_failed": False,
            "failure_reason": None,
            "preamble_used": [],
            "diagnosis": None,
            "suggested_fix": None,
            "fixable": None,
        }
    else:
        f_result = formalize_claim(raw_input, on_log=on_log)

    if not f_result["success"]:
        result = {
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
            "from_cache": False,
            "partial": False,
            "stop_reason": None,
            "tool_trace": [],
            "tactic_calls": [],
            "trace_schema_version": 1,
            "agent_summary": "",
            "agent_elapsed_seconds": 0.0,
            "axiom_info": None,
        }
        log_run(
            _build_run_log_entry(
                raw_input=raw_input,
                input_text=raw_input[:500] if preformalized_theorem is None else "",
                input_mode="raw_lean" if f_result["attempts"] == 0 else "latex_or_text",
                formalization={
                    "success": f_result["success"],
                    "attempts": f_result["attempts"],
                    "theorem_code": f_result.get("theorem_code", ""),
                    "errors": f_result.get("errors", []),
                    "model": "labs-leanstral-2603",
                    "formalization_failed": f_result.get("formalization_failed", False),
                    "failure_reason": f_result.get("failure_reason"),
                },
                proving={
                    "success": False,
                    "attempts_used": 0,
                    "proof_strategy": "",
                    "proof_tactics": "",
                    "tool_trace": [],
                    "tactic_calls": [],
                    "trace_schema_version": 1,
                    "agent_summary": "",
                },
                verification={
                    "success": False,
                    "errors": f_result.get("errors", []),
                    "warnings": [],
                },
                elapsed_seconds=result["elapsed_seconds"],
                from_cache=result["from_cache"],
                partial=result["partial"],
                stop_reason=result["stop_reason"],
            )
        )
        return result

    theorem_with_sorry = f_result["theorem_code"]
    pv_result = prove_and_verify(theorem_with_sorry, on_log=on_log)

    if pv_result["success"]:
        phase = "verified"
    elif pv_result["proof_generated"]:
        phase = "proved"
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
        "from_cache": False,
        "partial": pv_result["partial"],
        "stop_reason": pv_result["stop_reason"],
        "attempts_used": pv_result["attempts_used"],
        "tool_trace": pv_result["tool_trace"],
        "tactic_calls": pv_result["tactic_calls"],
        "trace_schema_version": pv_result["trace_schema_version"],
        "agent_summary": pv_result["agent_summary"],
        "agent_elapsed_seconds": pv_result["agent_elapsed_seconds"],
        "axiom_info": pv_result.get("axiom_info"),
    }

    if use_cache and result["success"]:
        result_cache.put(cache_key_input, result)

    log_run(
        _build_run_log_entry(
            raw_input=raw_input,
            input_text=raw_input[:500] if preformalized_theorem is None else "",
            input_mode="raw_lean" if f_result["attempts"] == 0 else "latex_or_text",
            formalization={
                "success": f_result["success"],
                "attempts": f_result["attempts"],
                "theorem_code": f_result["theorem_code"],
                "errors": f_result["errors"],
                "model": "labs-leanstral-2603",
                "formalization_failed": f_result["formalization_failed"],
                "failure_reason": f_result["failure_reason"],
            },
            proving={
                "success": pv_result["success"],
                "attempts_used": pv_result["attempts_used"],
                "proof_strategy": pv_result["proof_strategy"],
                "proof_tactics": pv_result["proof_tactics"],
                "tool_trace": pv_result["tool_trace"],
                "tactic_calls": pv_result["tactic_calls"],
                "trace_schema_version": pv_result["trace_schema_version"],
                "agent_summary": pv_result["agent_summary"],
            },
            verification={
                "success": pv_result["success"],
                "errors": pv_result["errors"],
                "warnings": pv_result["warnings"],
            },
            elapsed_seconds=result["elapsed_seconds"],
            from_cache=result["from_cache"],
            partial=result["partial"],
            stop_reason=result["stop_reason"],
        )
    )

    return result


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
        print("Run tests via: pytest tests/test_pipeline_smoke.py")
