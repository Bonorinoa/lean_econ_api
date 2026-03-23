"""Offline benchmark harness for LeanEcon research-preview evaluations."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from outcome_codes import formalize_error_code, verify_error_code
from pipeline import formalize_claim, run_pipeline

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "benchmarks"
SNAPSHOT_SCHEMA_VERSION = 2

MODE_FULL = "full"
MODE_FORMALIZER_ONLY = "formalizer-only"

LANE_RAW_CLAIM_FULL_API = "raw_claim_full_api"
LANE_THEOREM_STUB_VERIFY = "theorem_stub_verify"
LANE_RAW_LEAN_VERIFY = "raw_lean_verify"
LANE_FORMALIZER_ONLY = "formalizer_only"

LANE_LABELS = {
    LANE_RAW_CLAIM_FULL_API: "raw_claim -> full API",
    LANE_THEOREM_STUB_VERIFY: "theorem_stub -> verify",
    LANE_RAW_LEAN_VERIFY: "raw_lean -> verify",
    LANE_FORMALIZER_ONLY: "raw_claim -> formalizer-only gate",
}

FULL_MODE_LANES = (
    LANE_RAW_CLAIM_FULL_API,
    LANE_THEOREM_STUB_VERIFY,
    LANE_RAW_LEAN_VERIFY,
)
FORMALIZER_ONLY_LANES = (LANE_FORMALIZER_ONLY,)
WRAPPER_STAGES = {"prover_dispatch"}
STANDARD_BENCHMARK_FIELDS = {
    "id",
    "tier",
    "raw_claim",
    "theorem_stub",
    "raw_lean",
    "expected_category",
    "preamble_names",
    "provenance",
}


@dataclass(frozen=True)
class BenchmarkCase:
    """One benchmark record loaded from JSONL."""

    id: str
    tier: str
    raw_claim: str | None = None
    theorem_stub: str | None = None
    raw_lean: str | None = None
    expected_category: str | None = None
    preamble_names: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def applicable_lanes(self) -> list[str]:
        """Return the benchmark lanes that have enough input material to run."""
        lanes: list[str] = []
        if self.raw_claim:
            lanes.append(LANE_RAW_CLAIM_FULL_API)
        if self.theorem_stub:
            lanes.append(LANE_THEOREM_STUB_VERIFY)
        if self.raw_lean:
            lanes.append(LANE_RAW_LEAN_VERIFY)
        return lanes


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LeanEcon benchmark JSONL suites.")
    parser.add_argument("benchmark_jsonl", help="Path to a benchmark JSONL file.")
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="How many repetitions to run per applicable lane. Default: 3.",
    )
    parser.add_argument(
        "--mode",
        choices=[MODE_FULL, MODE_FORMALIZER_ONLY],
        default=MODE_FULL,
        help=(
            "`full` runs the verify lanes; `formalizer-only` runs the fast "
            "raw_claim formalization gate."
        ),
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Root directory for `snapshots/` and `reports/` outputs.",
    )
    parser.set_defaults(use_cache=False)
    parser.add_argument(
        "--use-cache",
        dest="use_cache",
        action="store_true",
        help="Allow verified-result cache hits during the benchmark run.",
    )
    parser.add_argument(
        "--no-cache",
        dest="use_cache",
        action="store_false",
        help="Disable verified-result cache hits during the benchmark run (default).",
    )
    return parser.parse_args(argv)


def _normalized_optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _error_code_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def load_benchmark_cases(path: Path) -> list[BenchmarkCase]:
    """Load and validate benchmark cases from JSONL."""
    cases: list[BenchmarkCase] = []
    seen_ids: set[str] = set()

    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"Line {line_number} is not a JSON object.")

        case_id = _normalized_optional_text(payload.get("id"))
        tier = _normalized_optional_text(payload.get("tier"))
        if not case_id:
            raise ValueError(f"Line {line_number} is missing a non-empty `id`.")
        if not tier:
            raise ValueError(f"Line {line_number} is missing a non-empty `tier`.")
        if case_id in seen_ids:
            raise ValueError(f"Duplicate benchmark id {case_id!r} on line {line_number}.")

        raw_claim = _normalized_optional_text(payload.get("raw_claim"))
        theorem_stub = _normalized_optional_text(payload.get("theorem_stub"))
        raw_lean = _normalized_optional_text(payload.get("raw_lean"))
        if not any((raw_claim, theorem_stub, raw_lean)):
            raise ValueError(
                f"Line {line_number} must include at least one of "
                "`raw_claim`, `theorem_stub`, or `raw_lean`."
            )

        preamble_names_raw = payload.get("preamble_names") or []
        if not isinstance(preamble_names_raw, list) or any(
            not isinstance(item, str) for item in preamble_names_raw
        ):
            raise ValueError(f"Line {line_number} has invalid `preamble_names`.")

        provenance_raw = payload.get("provenance") or {}
        if not isinstance(provenance_raw, dict):
            raise ValueError(f"Line {line_number} has invalid `provenance`.")

        metadata = {
            key: value
            for key, value in payload.items()
            if key not in STANDARD_BENCHMARK_FIELDS
        }

        cases.append(
            BenchmarkCase(
                id=case_id,
                tier=tier,
                raw_claim=raw_claim,
                theorem_stub=theorem_stub,
                raw_lean=raw_lean,
                expected_category=_normalized_optional_text(payload.get("expected_category")),
                preamble_names=[item.strip() for item in preamble_names_raw if item.strip()],
                provenance=provenance_raw,
                metadata=metadata,
            )
        )
        seen_ids.add(case_id)

    return cases


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 1)
    rank = (len(ordered) - 1) * percentile
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    lower_value = ordered[lower_index]
    upper_value = ordered[upper_index]
    fraction = rank - lower_index
    interpolated = lower_value + (upper_value - lower_value) * fraction
    return round(interpolated, 1)


def _pass_at_k(attempts: list[dict[str, Any]], k: int) -> bool | None:
    if len(attempts) < k:
        return None
    return any(bool(attempt.get("success")) for attempt in attempts[:k])


def _ordered_counter(counter: Counter[str]) -> dict[str, int]:
    return {key: count for key, count in counter.most_common()}


def _normalize_messages(values: Any, limit: int = 3) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item) for item in values[:limit] if str(item).strip()]


def _failure_stage_from_events(
    events: list[dict[str, Any]],
    *,
    success: bool,
    fallback: str | None = None,
) -> str | None:
    if success:
        return None
    error_stages = [
        str(event.get("stage"))
        for event in events
        if event.get("status") == "error" and event.get("stage")
    ]
    if error_stages:
        for stage in reversed(error_stages):
            if stage not in WRAPPER_STAGES:
                return stage
        return error_stages[-1]
    if fallback:
        return fallback
    if events:
        stage = events[-1].get("stage")
        if stage:
            return str(stage)
    return None


def _lane_attempt_summary(
    *,
    success: bool,
    latency_ms: float,
    failure_stage: str | None,
    error_code: str,
    stop_reason: str | None,
    from_cache: bool,
    phase: str | None,
    proof_generated: bool | None,
    formalization_success: bool,
    formalization_attempts: int,
    preamble_used: list[str] | None,
    errors: list[str],
    warnings: list[str],
    failure_reason: str | None = None,
    formalization_failed: bool = False,
    formalizer_telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "latency_ms": round(latency_ms, 1),
        "failure_stage": failure_stage,
        "error_code": error_code,
        "stop_reason": stop_reason,
        "from_cache": from_cache,
        "phase": phase,
        "proof_generated": proof_generated,
        "formalization_success": formalization_success,
        "formalization_attempts": formalization_attempts,
        "formalization_failed": formalization_failed,
        "failure_reason": failure_reason,
        "preamble_used": list(preamble_used or []),
        "errors": errors,
        "warnings": warnings,
        "formalizer_telemetry": dict(formalizer_telemetry or {}),
    }


def _run_formalizer_only_attempt(case: BenchmarkCase) -> dict[str, Any]:
    if not case.raw_claim:
        raise ValueError("formalizer-only lane requires `raw_claim`.")

    events: list[dict[str, Any]] = []

    def on_log(entry: dict[str, Any]) -> None:
        events.append(dict(entry))

    start = time.perf_counter()
    result = formalize_claim(
        case.raw_claim,
        on_log=on_log,
        preamble_names=case.preamble_names or None,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    success = bool(result.get("success"))
    return _lane_attempt_summary(
        success=success,
        latency_ms=latency_ms,
        failure_stage=_failure_stage_from_events(
            events,
            success=success,
            fallback="formalize",
        ),
        error_code=_error_code_value(formalize_error_code(result)),
        stop_reason=None,
        from_cache=False,
        phase="formalized" if success else "formalization_failed",
        proof_generated=None,
        formalization_success=success,
        formalization_attempts=int(result.get("attempts", 0)),
        preamble_used=result.get("preamble_used", []),
        errors=_normalize_messages(result.get("errors")),
        warnings=[],
        failure_reason=result.get("failure_reason"),
        formalization_failed=bool(result.get("formalization_failed")),
        formalizer_telemetry=result.get("formalizer_telemetry"),
    )


def _run_raw_claim_full_api_attempt(case: BenchmarkCase, *, use_cache: bool) -> dict[str, Any]:
    if not case.raw_claim:
        raise ValueError("raw_claim_full_api lane requires `raw_claim`.")

    events: list[dict[str, Any]] = []

    def on_log(entry: dict[str, Any]) -> None:
        events.append(dict(entry))

    start = time.perf_counter()
    formalization = formalize_claim(
        case.raw_claim,
        on_log=on_log,
        preamble_names=case.preamble_names or None,
    )
    formalization_success = bool(formalization.get("success"))
    if not formalization_success:
        latency_ms = (time.perf_counter() - start) * 1000
        return _lane_attempt_summary(
            success=False,
            latency_ms=latency_ms,
            failure_stage=_failure_stage_from_events(
                events,
                success=False,
                fallback="formalize",
            ),
            error_code=_error_code_value(formalize_error_code(formalization)),
            stop_reason=None,
            from_cache=False,
            phase="formalization_failed",
            proof_generated=False,
            formalization_success=False,
            formalization_attempts=int(formalization.get("attempts", 0)),
            preamble_used=formalization.get("preamble_used", []),
            errors=_normalize_messages(formalization.get("errors")),
            warnings=[],
            failure_reason=formalization.get("failure_reason"),
            formalization_failed=bool(formalization.get("formalization_failed")),
            formalizer_telemetry=formalization.get("formalizer_telemetry"),
        )

    verify_result = run_pipeline(
        raw_input=case.raw_claim,
        preformalized_theorem=str(formalization["theorem_code"]),
        on_log=on_log,
        use_cache=use_cache,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    success = bool(verify_result.get("success"))
    return _lane_attempt_summary(
        success=success,
        latency_ms=latency_ms,
        failure_stage=_failure_stage_from_events(
            events,
            success=success,
            fallback="verify",
        ),
        error_code=_error_code_value(verify_error_code(verify_result)),
        stop_reason=verify_result.get("stop_reason"),
        from_cache=bool(verify_result.get("from_cache")),
        phase=verify_result.get("phase"),
        proof_generated=verify_result.get("proof_generated"),
        formalization_success=True,
        formalization_attempts=int(formalization.get("attempts", 0)),
        preamble_used=formalization.get("preamble_used", []),
        errors=_normalize_messages(verify_result.get("errors")),
        warnings=_normalize_messages(verify_result.get("warnings")),
        formalizer_telemetry=formalization.get("formalizer_telemetry"),
    )


def _run_theorem_stub_attempt(case: BenchmarkCase, *, use_cache: bool) -> dict[str, Any]:
    if not case.theorem_stub:
        raise ValueError("theorem_stub_verify lane requires `theorem_stub`.")

    events: list[dict[str, Any]] = []

    def on_log(entry: dict[str, Any]) -> None:
        events.append(dict(entry))

    start = time.perf_counter()
    result = run_pipeline(
        raw_input=case.raw_claim or case.theorem_stub,
        preformalized_theorem=case.theorem_stub,
        on_log=on_log,
        use_cache=use_cache,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    success = bool(result.get("success"))
    return _lane_attempt_summary(
        success=success,
        latency_ms=latency_ms,
        failure_stage=_failure_stage_from_events(events, success=success, fallback="verify"),
        error_code=_error_code_value(verify_error_code(result)),
        stop_reason=result.get("stop_reason"),
        from_cache=bool(result.get("from_cache")),
        phase=result.get("phase"),
        proof_generated=result.get("proof_generated"),
        formalization_success=True,
        formalization_attempts=0,
        preamble_used=[],
        errors=_normalize_messages(result.get("errors")),
        warnings=_normalize_messages(result.get("warnings")),
        formalizer_telemetry=None,
    )


def _run_raw_lean_attempt(case: BenchmarkCase, *, use_cache: bool) -> dict[str, Any]:
    if not case.raw_lean:
        raise ValueError("raw_lean_verify lane requires `raw_lean`.")

    events: list[dict[str, Any]] = []

    def on_log(entry: dict[str, Any]) -> None:
        events.append(dict(entry))

    start = time.perf_counter()
    result = run_pipeline(
        raw_input=case.raw_lean,
        on_log=on_log,
        use_cache=use_cache,
    )
    latency_ms = (time.perf_counter() - start) * 1000
    success = bool(result.get("success"))
    formalization_attempts = int(result.get("formalization_attempts", 0))
    return _lane_attempt_summary(
        success=success,
        latency_ms=latency_ms,
        failure_stage=_failure_stage_from_events(
            events,
            success=success,
            fallback="verify",
        ),
        error_code=_error_code_value(verify_error_code(result)),
        stop_reason=result.get("stop_reason"),
        from_cache=bool(result.get("from_cache")),
        phase=result.get("phase"),
        proof_generated=result.get("proof_generated"),
        formalization_success=True,
        formalization_attempts=formalization_attempts,
        preamble_used=[],
        errors=_normalize_messages(result.get("errors")),
        warnings=_normalize_messages(result.get("warnings")),
        formalizer_telemetry=None,
    )


def _run_attempt(case: BenchmarkCase, lane: str, *, use_cache: bool) -> dict[str, Any]:
    if lane == LANE_FORMALIZER_ONLY:
        return _run_formalizer_only_attempt(case)
    if lane == LANE_RAW_CLAIM_FULL_API:
        return _run_raw_claim_full_api_attempt(case, use_cache=use_cache)
    if lane == LANE_THEOREM_STUB_VERIFY:
        return _run_theorem_stub_attempt(case, use_cache=use_cache)
    if lane == LANE_RAW_LEAN_VERIFY:
        return _run_raw_lean_attempt(case, use_cache=use_cache)
    raise ValueError(f"Unsupported benchmark lane: {lane}")


def _summarize_attempts(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(attempt["latency_ms"]) for attempt in attempts]
    failure_stage_counts = Counter(
        str(attempt["failure_stage"])
        for attempt in attempts
        if attempt.get("failure_stage")
    )
    error_code_counts = Counter(
        str(attempt["error_code"])
        for attempt in attempts
        if attempt.get("error_code")
    )
    stop_reason_counts = Counter(
        str(attempt["stop_reason"])
        for attempt in attempts
        if attempt.get("stop_reason")
    )
    validation_method_counts = Counter(
        str(telemetry.get("validation_method"))
        for attempt in attempts
        for telemetry in [attempt.get("formalizer_telemetry") or {}]
        if telemetry.get("validation_method")
    )
    repair_bucket_counts = Counter(
        str(bucket)
        for attempt in attempts
        for telemetry in [attempt.get("formalizer_telemetry") or {}]
        for bucket in telemetry.get("repair_buckets", [])
        if bucket
    )
    retrieval_source_counts = Counter()
    for attempt in attempts:
        telemetry = attempt.get("formalizer_telemetry") or {}
        source_counts = telemetry.get("retrieval", {}).get("source_counts", {}) or {}
        for source, count in source_counts.items():
            if count:
                retrieval_source_counts[str(source)] += int(count)
    return {
        "attempts_run": len(attempts),
        "successful_attempts": sum(1 for attempt in attempts if attempt.get("success")),
        "pass_at_1": _pass_at_k(attempts, 1),
        "pass_at_3": _pass_at_k(attempts, 3),
        "pass_at_5": _pass_at_k(attempts, 5),
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "failure_stage_counts": _ordered_counter(failure_stage_counts),
        "error_code_counts": _ordered_counter(error_code_counts),
        "stop_reason_counts": _ordered_counter(stop_reason_counts),
        "validation_method_counts": _ordered_counter(validation_method_counts),
        "repair_bucket_counts": _ordered_counter(repair_bucket_counts),
        "retrieval_source_counts": _ordered_counter(retrieval_source_counts),
        "cache_hits": sum(1 for attempt in attempts if attempt.get("from_cache")),
    }


def _skipped_lane_record(reason: str) -> dict[str, Any]:
    return {
        "label": None,
        "applicable": False,
        "skipped_reason": reason,
        "attempts": [],
        "summary": {
            "attempts_run": 0,
            "successful_attempts": 0,
            "pass_at_1": None,
            "pass_at_3": None,
            "pass_at_5": None,
            "latency_ms": {"p50": None, "p95": None},
            "failure_stage_counts": {},
            "error_code_counts": {},
            "stop_reason_counts": {},
            "validation_method_counts": {},
            "repair_bucket_counts": {},
            "retrieval_source_counts": {},
            "cache_hits": 0,
        },
    }


def _lane_applicable(case: BenchmarkCase, lane: str) -> tuple[bool, str | None]:
    if lane == LANE_FORMALIZER_ONLY:
        return (case.raw_claim is not None, "missing_raw_claim")
    if lane == LANE_RAW_CLAIM_FULL_API:
        return (case.raw_claim is not None, "missing_raw_claim")
    if lane == LANE_THEOREM_STUB_VERIFY:
        return (case.theorem_stub is not None, "missing_theorem_stub")
    if lane == LANE_RAW_LEAN_VERIFY:
        return (case.raw_lean is not None, "missing_raw_lean")
    return (False, "unsupported_lane")


def _average_optional_booleans(values: list[bool | None]) -> float | None:
    concrete = [value for value in values if value is not None]
    if not concrete:
        return None
    return round(sum(1 for value in concrete if value) / len(concrete), 3)


def _aggregate_lane(case_records: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    applicable_records = [
        record["lanes"][lane]
        for record in case_records
        if record["lanes"][lane]["applicable"]
    ]
    all_attempts = [
        attempt
        for record in applicable_records
        for attempt in record["attempts"]
    ]
    failure_stage_counts = Counter(
        str(attempt["failure_stage"])
        for attempt in all_attempts
        if attempt.get("failure_stage")
    )
    error_code_counts = Counter(
        str(attempt["error_code"])
        for attempt in all_attempts
        if attempt.get("error_code")
    )
    stop_reason_counts = Counter(
        str(attempt["stop_reason"])
        for attempt in all_attempts
        if attempt.get("stop_reason")
    )
    validation_method_counts = Counter(
        str(telemetry.get("validation_method"))
        for attempt in all_attempts
        for telemetry in [attempt.get("formalizer_telemetry") or {}]
        if telemetry.get("validation_method")
    )
    repair_bucket_counts = Counter(
        str(bucket)
        for attempt in all_attempts
        for telemetry in [attempt.get("formalizer_telemetry") or {}]
        for bucket in telemetry.get("repair_buckets", [])
        if bucket
    )
    retrieval_source_counts = Counter()
    for attempt in all_attempts:
        telemetry = attempt.get("formalizer_telemetry") or {}
        source_counts = telemetry.get("retrieval", {}).get("source_counts", {}) or {}
        for source, count in source_counts.items():
            if count:
                retrieval_source_counts[str(source)] += int(count)
    latencies = [float(attempt["latency_ms"]) for attempt in all_attempts]
    pass_at_1_values = [record["summary"]["pass_at_1"] for record in applicable_records]
    pass_at_3_values = [record["summary"]["pass_at_3"] for record in applicable_records]
    pass_at_5_values = [record["summary"]["pass_at_5"] for record in applicable_records]

    return {
        "label": LANE_LABELS[lane],
        "applicable_cases": len(applicable_records),
        "attempts_run": len(all_attempts),
        "successful_attempts": sum(1 for attempt in all_attempts if attempt.get("success")),
        "pass_at_1": _average_optional_booleans(pass_at_1_values),
        "pass_at_3": _average_optional_booleans(pass_at_3_values),
        "pass_at_5": _average_optional_booleans(pass_at_5_values),
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "failure_stage_counts": _ordered_counter(failure_stage_counts),
        "error_code_counts": _ordered_counter(error_code_counts),
        "stop_reason_counts": _ordered_counter(stop_reason_counts),
        "validation_method_counts": _ordered_counter(validation_method_counts),
        "repair_bucket_counts": _ordered_counter(repair_bucket_counts),
        "retrieval_source_counts": _ordered_counter(retrieval_source_counts),
        "cache_hits": sum(1 for attempt in all_attempts if attempt.get("from_cache")),
    }


def build_snapshot(
    *,
    benchmark_path: Path,
    cases: list[BenchmarkCase],
    repetitions: int,
    mode: str,
    use_cache: bool,
) -> dict[str, Any]:
    """Run the benchmark suite and return the structured snapshot payload."""
    selected_lanes = FULL_MODE_LANES if mode == MODE_FULL else FORMALIZER_ONLY_LANES
    case_records: list[dict[str, Any]] = []

    for index, case in enumerate(cases, start=1):
        lane_records: dict[str, Any] = {}
        for lane in selected_lanes:
            applicable, skipped_reason = _lane_applicable(case, lane)
            if not applicable:
                lane_records[lane] = _skipped_lane_record(skipped_reason or "not_applicable")
                lane_records[lane]["label"] = LANE_LABELS[lane]
                continue

            attempts: list[dict[str, Any]] = []
            for run_index in range(1, repetitions + 1):
                attempt = _run_attempt(case, lane, use_cache=use_cache)
                attempt["run_index"] = run_index
                attempts.append(attempt)

            lane_records[lane] = {
                "label": LANE_LABELS[lane],
                "applicable": True,
                "skipped_reason": None,
                "attempts": attempts,
                "summary": _summarize_attempts(attempts),
            }

        case_records.append(
            {
                "index": index,
                "id": case.id,
                "tier": case.tier,
                "raw_claim": case.raw_claim,
                "expected_category": case.expected_category,
                "preamble_names": case.preamble_names,
                "provenance": case.provenance,
                "metadata": case.metadata,
                "lanes": lane_records,
            }
        )

    summary = {
        "total_cases": len(case_records),
        "lanes": {
            lane: _aggregate_lane(case_records, lane)
            for lane in selected_lanes
        },
    }

    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_file": str(benchmark_path),
        "config": {
            "mode": mode,
            "repetitions": repetitions,
            "use_cache": use_cache,
            "lane_order": list(selected_lanes),
        },
        "summary": summary,
        "cases": case_records,
    }


def _format_pass_metric(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}"


def _format_latency(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}"


def render_report(snapshot: dict[str, Any]) -> str:
    """Render a compact markdown report from a benchmark snapshot."""
    config = snapshot["config"]
    summary = snapshot["summary"]
    lines = [
        "# LeanEcon Benchmark Report",
        "",
        f"Generated: {snapshot['generated_at']}",
        f"Benchmark file: `{snapshot['benchmark_file']}`",
        f"Mode: `{config['mode']}`",
        f"Repetitions: `{config['repetitions']}`",
        f"Cache enabled: `{config['use_cache']}`",
        "",
        "## Aggregate Lane Summary",
        "",
        "| Lane | Cases | Attempts | pass@1 | pass@3 | pass@5 | p50 ms | p95 ms | Cache hits |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for lane in config["lane_order"]:
        lane_summary = summary["lanes"][lane]
        lines.append(
            "| "
            f"{LANE_LABELS[lane]} | "
            f"{lane_summary['applicable_cases']} | "
            f"{lane_summary['attempts_run']} | "
            f"{_format_pass_metric(lane_summary['pass_at_1'])} | "
            f"{_format_pass_metric(lane_summary['pass_at_3'])} | "
            f"{_format_pass_metric(lane_summary['pass_at_5'])} | "
            f"{_format_latency(lane_summary['latency_ms']['p50'])} | "
            f"{_format_latency(lane_summary['latency_ms']['p95'])} | "
            f"{lane_summary['cache_hits']} |"
        )

    for lane in config["lane_order"]:
        lane_summary = summary["lanes"][lane]
        lines.extend(
            [
                "",
                f"### {LANE_LABELS[lane]}",
                "",
                f"- Failure stages: {lane_summary['failure_stage_counts'] or '(none)'}",
                f"- Error codes: {lane_summary['error_code_counts'] or '(none)'}",
                f"- Stop reasons: {lane_summary['stop_reason_counts'] or '(none)'}",
                f"- Validation methods: {lane_summary['validation_method_counts'] or '(none)'}",
                f"- Repair buckets: {lane_summary['repair_bucket_counts'] or '(none)'}",
                f"- Retrieval sources: {lane_summary['retrieval_source_counts'] or '(none)'}",
            ]
        )

    lines.extend(["", "## Per-Case Summary", ""])
    for case in snapshot["cases"]:
        lines.extend(
            [
                f"### {case['id']}",
                "",
                f"- Tier: {case['tier']}",
                f"- Expected category: {case.get('expected_category') or '(unspecified)'}",
            ]
        )
        if case.get("raw_claim"):
            lines.append(f"- Raw claim: {case['raw_claim']}")
        if case.get("preamble_names"):
            lines.append(f"- Preambles: {', '.join(case['preamble_names'])}")
        for lane in config["lane_order"]:
            lane_record = case["lanes"][lane]
            if not lane_record["applicable"]:
                lines.append(
                    f"- {LANE_LABELS[lane]}: skipped ({lane_record['skipped_reason']})"
                )
                continue
            lane_summary = lane_record["summary"]
            lines.append(
                f"- {LANE_LABELS[lane]}: "
                f"pass@1={lane_summary['pass_at_1']}, "
                f"pass@3={lane_summary['pass_at_3']}, "
                f"pass@5={lane_summary['pass_at_5']}, "
                f"p50={_format_latency(lane_summary['latency_ms']['p50'])} ms, "
                f"p95={_format_latency(lane_summary['latency_ms']['p95'])} ms, "
                f"failure_stages={lane_summary['failure_stage_counts'] or '(none)'}, "
                f"error_codes={lane_summary['error_code_counts'] or '(none)'}, "
                f"stop_reasons={lane_summary['stop_reason_counts'] or '(none)'}, "
                f"validation_methods={lane_summary['validation_method_counts'] or '(none)'}, "
                f"repair_buckets={lane_summary['repair_bucket_counts'] or '(none)'}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def load_latest_snapshot(snapshot_dir: Path | None = None) -> dict[str, Any] | None:
    """Return the newest benchmark snapshot, if one exists."""
    directory = snapshot_dir or (DEFAULT_OUTPUT_ROOT / "snapshots")
    candidates = sorted(directory.glob("*.json"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        return None
    latest = candidates[-1]
    return json.loads(latest.read_text(encoding="utf-8"))


def latest_snapshot_summary(snapshot_dir: Path | None = None) -> dict[str, Any] | None:
    """Return a summary-only view of the newest benchmark snapshot."""
    snapshot = load_latest_snapshot(snapshot_dir=snapshot_dir)
    if snapshot is None:
        return None
    return {
        "generated_at": snapshot.get("generated_at"),
        "benchmark_file": snapshot.get("benchmark_file"),
        "config": snapshot.get("config", {}),
        "summary": snapshot.get("summary", {}),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.repetitions < 1:
        raise ValueError("--repetitions must be at least 1.")
    if not os.environ.get("MISTRAL_API_KEY"):
        print("MISTRAL_API_KEY is required to run benchmarks.")
        return 1

    benchmark_path = Path(args.benchmark_jsonl).resolve()
    cases = load_benchmark_cases(benchmark_path)

    output_root = Path(args.output_root).resolve()
    snapshots_dir = output_root / "snapshots"
    reports_dir = output_root / "reports"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    snapshot = build_snapshot(
        benchmark_path=benchmark_path,
        cases=cases,
        repetitions=args.repetitions,
        mode=args.mode,
        use_cache=args.use_cache,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = benchmark_path.stem
    mode_label = args.mode.replace("-", "_")
    snapshot_path = snapshots_dir / f"{stem}_{mode_label}_{timestamp}.json"
    report_path = reports_dir / f"{stem}_{mode_label}_{timestamp}.md"

    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    report_path.write_text(render_report(snapshot), encoding="utf-8")

    print(f"Wrote benchmark snapshot to {snapshot_path}")
    print(f"Wrote benchmark report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
