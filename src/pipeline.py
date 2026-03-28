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
from model_config import LEANSTRAL_MODEL
from prover_backend import get_prover
from provider_telemetry import collect_provider_calls, summarize_provider_calls
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
    provider_telemetry: dict[str, Any]
    budget: dict[str, Any] | None


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
    provider_telemetry: dict[str, Any] | None = None,
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
    if provider_telemetry is not None:
        entry["provider_telemetry"] = provider_telemetry
        entry["estimated_cost_base_usd"] = provider_telemetry.get("estimated_cost_base_usd")
        entry["estimated_cost_stress_usd"] = provider_telemetry.get("estimated_cost_stress_usd")
        entry["provider_call_count"] = provider_telemetry.get("provider_call_count")
        entry["llm_call_count"] = provider_telemetry.get("llm_call_count")
        entry["usage_present"] = provider_telemetry.get("usage_present")
        entry["local_only"] = provider_telemetry.get("local_only")
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
        on_log(
            {
                "stage": stage,
                "message": message,
                "data": data,
                "status": status,
                "elapsed_ms": elapsed_ms,
            }
        )
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


def _is_raw_lean_input(raw_input: str) -> bool:
    """Detect theorem-stub input that can skip the natural-language formalizer."""
    return "import Mathlib" in raw_input or (":= by" in raw_input and "sorry" in raw_input)


def _formalization_model_label(formalization: dict[str, Any]) -> str:
    telemetry = formalization.get("formalizer_telemetry") or {}
    model = telemetry.get("model")
    if model:
        return str(model)
    if formalization.get("attempts", 0) == 0:
        return "raw_lean_bypass"
    return LEANSTRAL_MODEL


def _empty_formalization_telemetry(model_label: str) -> dict[str, Any]:
    return {
        "model": model_label,
        "cache_hit": False,
        "cache_namespace": None,
        "model_calls": 0,
        "validation_method": None,
        "validation_methods": [],
        "validation_fallback_reasons": [],
        "repair_buckets": [],
        "last_repair_bucket": None,
        "deterministic_repairs_applied": [],
        "selected_preambles": [],
        "explicit_preambles": [],
        "auto_preambles": [],
        "retrieval": {},
        "mcp": {},
        "provider_telemetry": summarize_provider_calls([]),
    }


def _empty_formalization_context(model_label: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "cache_hit": False,
        "source": model_label,
        "claim_text": "",
        "claim_components": [],
        "selected_preambles": [],
        "explicit_preambles": [],
        "auto_preambles": [],
        "preamble_imports": [],
        "candidate_imports": [],
        "candidate_identifiers": [],
        "search_terms": [],
        "shape_guidance": [],
        "retrieval_notes": [],
        "retrieval": {
            "source_counts": {},
            "mcp_enabled": False,
            "mcp_skip_reason": None,
            "mcp_hits": [],
        },
        "validation": {
            "method": None,
            "methods": [],
            "fallback_reasons": [],
        },
        "repairs": {
            "repair_buckets": [],
            "deterministic_repairs_applied": [],
        },
    }


def _formalization_log_payload(formalization: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": formalization.get("success", False),
        "attempts": formalization.get("attempts", 0),
        "theorem_code": formalization.get("theorem_code", ""),
        "errors": formalization.get("errors", []),
        "model": _formalization_model_label(formalization),
        "formalization_failed": formalization.get("formalization_failed", False),
        "failure_reason": formalization.get("failure_reason"),
        "formalizer_telemetry": formalization.get("formalizer_telemetry", {}),
    }


def _combined_provider_telemetry(*sources: Any) -> dict[str, Any]:
    """Merge provider telemetry from one or more stage telemetry payloads."""
    return summarize_provider_calls(collect_provider_calls(*sources))


def _raw_lean_formalization_result(raw_input: str) -> dict[str, Any]:
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
        "formalizer_telemetry": _empty_formalization_telemetry("raw_lean_bypass"),
        "formalization_context": _empty_formalization_context("raw_lean_bypass"),
    }


def _preformalized_result(
    theorem_code: str,
    formalization_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": True,
        "theorem_code": theorem_code.strip(),
        "attempts": 0,
        "errors": [],
        "formalization_failed": False,
        "failure_reason": None,
        "preamble_used": [],
        "diagnosis": None,
        "suggested_fix": None,
        "fixable": None,
        "formalizer_telemetry": _empty_formalization_telemetry("preformalized_input"),
        "formalization_context": formalization_context
        or _empty_formalization_context("preformalized_input"),
    }


def _failed_pipeline_result(
    f_result: dict[str, Any],
    *,
    started_at: float,
    provider_telemetry: dict[str, Any],
) -> dict[str, Any]:
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
        "elapsed_seconds": time.time() - started_at,
        "from_cache": False,
        "partial": False,
        "stop_reason": None,
        "tool_trace": [],
        "tactic_calls": [],
        "trace_schema_version": 1,
        "agent_summary": "",
        "agent_elapsed_seconds": 0.0,
        "axiom_info": None,
        "provider_telemetry": provider_telemetry,
        "formalization_context": f_result.get("formalization_context"),
        "budget": None,
    }


def _successful_pipeline_result(
    *,
    theorem_with_sorry: str,
    f_result: dict[str, Any],
    pv_result: ProveResult,
    started_at: float,
    provider_telemetry: dict[str, Any],
) -> dict[str, Any]:
    if pv_result["success"]:
        phase = "verified"
    elif pv_result["proof_generated"]:
        phase = "proved"
    else:
        phase = "failed"

    return {
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
        "elapsed_seconds": time.time() - started_at,
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
        "provider_telemetry": provider_telemetry,
        "formalization_context": f_result.get("formalization_context"),
        "budget": pv_result.get("budget"),
    }


def formalize_claim(
    raw_input: str,
    on_log: callable | None = None,
    preamble_names: list[str] | None = None,
    use_cache: bool = True,
) -> dict:
    """
    Phase 1: parse + formalize only. Returns the theorem statement for user review.

    Auto-detects raw Lean input and skips formalization if detected.
    """
    if _is_raw_lean_input(raw_input):
        _log(on_log, "parse", "Raw Lean input detected — skipping formalization", status="done")
        return _raw_lean_formalization_result(raw_input)

    _log(on_log, "parse", "Cleaning input...", status="running")
    t_parse = time.time()
    parsed = parse_claim(raw_input)
    _log(on_log, "parse", "Input cleaned", status="done", elapsed_ms=(time.time() - t_parse) * 1000)

    _log(on_log, "formalize", "Calling Leanstral to formalize claim...", status="running")
    t_formalize = time.time()
    result = formalize(
        parsed["text"],
        on_log=on_log,
        preamble_names=preamble_names,
        use_cache=use_cache,
    )
    formalize_elapsed_ms = (time.time() - t_formalize) * 1000

    if result["formalization_failed"]:
        _log(
            on_log,
            "formalize",
            f"Formalization failed: {result['failure_reason']}",
            status="error",
            elapsed_ms=formalize_elapsed_ms,
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
    formalization_context: dict[str, Any] | None = None,
    reasoning_preset: str | None = None,
    budget_overrides: dict[str, Any] | None = None,
) -> ProveResult:
    """Phase 2: proof generation plus final Lean verification."""
    prover = get_prover(prover_name)
    success = False
    _log(on_log, "prover_dispatch", f"Using prover: {prover.name}", status="running")
    t_prover = time.time()
    result = prover.prove(
        theorem_with_sorry,
        on_log=on_log,
        formalization_context=formalization_context,
        reasoning_preset=reasoning_preset,
        budget_overrides=budget_overrides,
    )
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
        "provider_telemetry": result.get("provider_telemetry", summarize_provider_calls([])),
        "budget": result.get("budget"),
    }


def run_pipeline(
    raw_input: str,
    on_log: callable | None = None,
    preformalized_theorem: str | None = None,
    formalization_context: dict[str, Any] | None = None,
    reasoning_preset: str | None = None,
    budget_overrides: dict[str, Any] | None = None,
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
            _log(
                on_log,
                "cache",
                "Cache hit — returning verified result",
                status="done",
                elapsed_ms=0.0,
            )
            cached["elapsed_seconds"] = 0.0
            cached["from_cache"] = True
            cached_provider_telemetry = dict(cached.get("provider_telemetry", {}))
            if cached_provider_telemetry:
                cached["cached_provider_telemetry"] = cached_provider_telemetry
            cached["provider_telemetry"] = summarize_provider_calls([])
            cached.setdefault("partial", False)
            cached.setdefault("stop_reason", None)
            cached.setdefault("tool_trace", [])
            cached.setdefault("tactic_calls", [])
            cached.setdefault("trace_schema_version", 1)
            cached.setdefault("agent_summary", "")
            cached.setdefault("agent_elapsed_seconds", 0.0)
            cached.setdefault("budget", None)
            cached.setdefault("formalization_context", None)
            cached_theorem = (
                cached.get("theorem_statement") or cached.get("lean_code") or cache_key_input
            )
            cached_formalization_telemetry = _empty_formalization_telemetry("cache_replay")
            cached_formalization_telemetry["cache_hit"] = True
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
                        "formalizer_telemetry": cached_formalization_telemetry,
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
                        "budget": cached.get("budget"),
                        "provider_telemetry": summarize_provider_calls([]),
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
                    provider_telemetry=summarize_provider_calls([]),
                    cache_replay=True,
                )
            )
            return cached

    if preformalized_theorem is not None:
        f_result = _preformalized_result(
            preformalized_theorem,
            formalization_context=formalization_context,
        )
    else:
        f_result = formalize_claim(raw_input, on_log=on_log, use_cache=use_cache)

    if not f_result["success"]:
        provider_telemetry = _combined_provider_telemetry(
            f_result.get("formalizer_telemetry", {}).get("provider_telemetry"),
        )
        result = _failed_pipeline_result(
            f_result,
            started_at=start,
            provider_telemetry=provider_telemetry,
        )
        log_run(
            _build_run_log_entry(
                raw_input=raw_input,
                input_text=raw_input[:500] if preformalized_theorem is None else "",
                input_mode="raw_lean" if f_result["attempts"] == 0 else "latex_or_text",
                formalization=_formalization_log_payload(f_result),
                proving={
                    "success": False,
                    "attempts_used": 0,
                    "proof_strategy": "",
                    "proof_tactics": "",
                    "tool_trace": [],
                    "tactic_calls": [],
                    "trace_schema_version": 1,
                    "agent_summary": "",
                    "budget": None,
                    "provider_telemetry": summarize_provider_calls([]),
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
                provider_telemetry=result["provider_telemetry"],
            )
        )
        return result

    theorem_with_sorry = f_result["theorem_code"]
    pv_result = prove_and_verify(
        theorem_with_sorry,
        on_log=on_log,
        formalization_context=f_result.get("formalization_context"),
        reasoning_preset=reasoning_preset,
        budget_overrides=budget_overrides,
    )
    provider_telemetry = _combined_provider_telemetry(
        f_result.get("formalizer_telemetry", {}).get("provider_telemetry"),
        pv_result.get("provider_telemetry"),
    )
    result = _successful_pipeline_result(
        theorem_with_sorry=theorem_with_sorry,
        f_result=f_result,
        pv_result=pv_result,
        started_at=start,
        provider_telemetry=provider_telemetry,
    )

    if use_cache and result["success"]:
        result_cache.put(cache_key_input, result)

    log_run(
        _build_run_log_entry(
            raw_input=raw_input,
            input_text=raw_input[:500] if preformalized_theorem is None else "",
            input_mode="raw_lean" if f_result["attempts"] == 0 else "latex_or_text",
            formalization=_formalization_log_payload(f_result),
            proving={
                "success": pv_result["success"],
                "attempts_used": pv_result["attempts_used"],
                "proof_strategy": pv_result["proof_strategy"],
                "proof_tactics": pv_result["proof_tactics"],
                "tool_trace": pv_result["tool_trace"],
                "tactic_calls": pv_result["tactic_calls"],
                "trace_schema_version": pv_result["trace_schema_version"],
                "agent_summary": pv_result["agent_summary"],
                "budget": pv_result.get("budget"),
                "provider_telemetry": pv_result["provider_telemetry"],
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
            provider_telemetry=result["provider_telemetry"],
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
