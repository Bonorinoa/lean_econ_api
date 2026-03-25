"""Run staged claim evaluations with budget-aware defaults."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from eval_metrics import aggregate_trace_metrics  # noqa: E402
from pipeline import formalize_claim, run_pipeline  # noqa: E402
from semantic_alignment import grade_semantic_alignment  # noqa: E402

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "uncharted_evals"
PROFILE_DEFAULTS = {
    "ci": {
        "pass_k": 1,
        "attempt_delay": 0,
        "semantic_grading": "off",
        "stage_mode": "dataset",
    },
    "core": {
        "pass_k": 1,
        "attempt_delay": 0,
        "semantic_grading": "on",
        "stage_mode": "dataset",
    },
    "frontier": {
        "pass_k": 5,
        "attempt_delay": 5,
        "semantic_grading": "on",
        "stage_mode": "e2e",
    },
}
STAGE_ALIASES = {
    "e2e": "e2e",
    "end_to_end": "e2e",
    "formalization": "formalization",
    "formalize": "formalization",
    "prove": "prove",
    "proof": "prove",
    "verification": "prove",
    "verify": "prove",
}
EXPECTATION_VALUES = {"verify", "formalize", "fail_gracefully"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LeanEcon claim evaluations.")
    parser.add_argument("claims_jsonl", help="JSONL file of claims to evaluate.")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_DEFAULTS),
        default="ci",
        help=(
            "Preset for cost/coverage tradeoffs. "
            "`ci` is cheap, `core` adds semantic grading, `frontier` restores "
            "the previous pass@k-heavy end-to-end behavior."
        ),
    )
    parser.add_argument(
        "--pass-k",
        type=int,
        default=None,
        help="Maximum number of proving attempts per proof-stage case.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Directory under which artifacts should be written.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on the number of claims to process.",
    )
    parser.add_argument(
        "--attempt-delay",
        type=int,
        default=None,
        help="Seconds to wait between proving attempts.",
    )
    parser.add_argument(
        "--semantic-grading",
        choices=["on", "off"],
        default=None,
        help="Override the profile default for semantic-alignment grading.",
    )
    parser.add_argument(
        "--stage-mode",
        choices=["dataset", "formalization", "prove", "e2e"],
        default=None,
        help=(
            "How to choose evaluation stages. `dataset` respects per-case "
            "`eval_stage`, `theorem_code`, and `expect` hints."
        ),
    )
    return parser.parse_args()


def _resolve_config(args: argparse.Namespace) -> dict[str, Any]:
    defaults = PROFILE_DEFAULTS[args.profile]
    pass_k = args.pass_k if args.pass_k is not None else defaults["pass_k"]
    attempt_delay = (
        args.attempt_delay if args.attempt_delay is not None else defaults["attempt_delay"]
    )
    semantic_grading = args.semantic_grading or defaults["semantic_grading"]
    stage_mode = args.stage_mode or defaults["stage_mode"]

    if pass_k < 1:
        raise ValueError("--pass-k must be at least 1.")
    if attempt_delay < 0:
        raise ValueError("--attempt-delay must be non-negative.")

    return {
        "profile": args.profile,
        "pass_k": pass_k,
        "attempt_delay": attempt_delay,
        "semantic_grading": semantic_grading,
        "stage_mode": stage_mode,
    }


def _load_claims(path: Path) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError(f"Line {line_number} is not a JSON object.")
        raw_claim = payload.get("raw_claim")
        theorem_code = payload.get("theorem_code") or payload.get("preformalized_theorem")
        if not isinstance(raw_claim, str) and not isinstance(theorem_code, str):
            raise ValueError(
                "Line "
                f"{line_number} must include `raw_claim` or "
                "`theorem_code`/`preformalized_theorem`."
            )
        expectation = payload.get("expect")
        if expectation is not None:
            normalized = str(expectation).strip().lower()
            if normalized not in EXPECTATION_VALUES:
                raise ValueError(f"Line {line_number} has unsupported `expect={expectation!r}`.")
        stage = payload.get("eval_stage")
        if stage is not None and _normalize_stage(stage) is None:
            raise ValueError(f"Line {line_number} has unsupported `eval_stage={stage!r}`.")
        claims.append(payload)
    return claims


def _normalize_stage(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return STAGE_ALIASES.get(normalized)


def _normalize_expectation(payload: dict[str, Any]) -> str | None:
    value = payload.get("expect")
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized not in EXPECTATION_VALUES:
        raise ValueError(f"Unsupported expectation: {value!r}")
    return normalized


def _preloaded_theorem_code(payload: dict[str, Any]) -> str:
    theorem_code = payload.get("theorem_code") or payload.get("preformalized_theorem") or ""
    if isinstance(theorem_code, str):
        return theorem_code.strip()
    return ""


def _infer_case_stage(payload: dict[str, Any], stage_mode: str) -> str:
    explicit_stage = _normalize_stage(payload.get("eval_stage"))
    if stage_mode != "dataset":
        return stage_mode
    if explicit_stage is not None:
        return explicit_stage
    if _preloaded_theorem_code(payload):
        return "prove"

    expectation = _normalize_expectation(payload)
    if expectation == "verify":
        return "e2e"
    if expectation in {"formalize", "fail_gracefully"}:
        return "formalization"
    return "e2e"


def _claim_id(payload: dict[str, Any], index: int) -> str:
    value = payload.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"claim_{index:03d}"


def _semantic_placeholder(verdict: str, rationale: str) -> dict[str, Any]:
    return {
        "score": None,
        "verdict": verdict,
        "rationale": rationale,
        "trivialization_flags": [],
        "generated": False,
    }


def _synthetic_formalization_result(theorem_code: str) -> dict[str, Any]:
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
    }


def _case_outcome(
    *,
    evaluation_stage: str,
    formalization: dict[str, Any],
    pass_at_k_success: bool,
    runner_error: dict[str, str] | None,
) -> str:
    if runner_error is not None:
        return "runner_error"
    if pass_at_k_success:
        return "verified"
    if not formalization.get("success"):
        return "formalization_failed"
    if evaluation_stage == "formalization":
        return "formalized"
    return "proof_failed"


def _expectation_met(
    *,
    expected_outcome: str | None,
    formalization: dict[str, Any],
    pass_at_k_success: bool,
    runner_error: dict[str, str] | None,
) -> bool | None:
    if expected_outcome is None:
        return None
    if expected_outcome == "verify":
        return pass_at_k_success
    if expected_outcome == "formalize":
        return bool(formalization.get("success"))
    return runner_error is None


def _evaluate_case(
    *,
    claim: dict[str, Any],
    index: int,
    config: dict[str, Any],
) -> dict[str, Any]:
    claim_id = _claim_id(claim, index)
    raw_claim = str(claim.get("raw_claim") or "").strip()
    evaluation_stage = _infer_case_stage(claim, config["stage_mode"])
    expected_outcome = _normalize_expectation(claim)
    theorem_code = _preloaded_theorem_code(claim)

    preamble_names = claim.get("preamble_names")
    if not isinstance(preamble_names, list):
        preamble_names = None

    formalization: dict[str, Any] = {
        "success": False,
        "theorem_code": theorem_code,
        "attempts": 0,
        "errors": [],
        "formalization_failed": False,
        "failure_reason": None,
        "preamble_used": [],
        "diagnosis": None,
        "suggested_fix": None,
        "fixable": None,
    }
    semantic_grade = _semantic_placeholder("disabled", "Semantic grading disabled by profile.")
    attempts: list[dict[str, Any]] = []
    skipped_proving_reason: str | None = None
    runner_error: dict[str, str] | None = None

    try:
        if evaluation_stage == "prove":
            if not theorem_code:
                raise ValueError(
                    "Evaluation stage `prove` requires `theorem_code` or `preformalized_theorem`."
                )
            formalization = _synthetic_formalization_result(theorem_code)
        else:
            if not raw_claim:
                raise ValueError("Claim is missing a non-empty `raw_claim`.")
            formalization = formalize_claim(
                raw_claim,
                preamble_names=preamble_names,
            )

        if formalization["success"] and config["semantic_grading"] == "on":
            if raw_claim:
                semantic_grade = grade_semantic_alignment(raw_claim, formalization["theorem_code"])
            else:
                semantic_grade = _semantic_placeholder(
                    "skipped",
                    "Semantic grading requires `raw_claim` alongside the theorem.",
                )
        elif not formalization["success"]:
            semantic_grade = _semantic_placeholder(
                "formalization_failed",
                "Semantic grading skipped because formalization failed.",
            )

        should_prove = evaluation_stage in {"prove", "e2e"} and formalization["success"]
        theorem_to_prove = formalization["theorem_code"]
        if should_prove:
            for attempt_number in range(1, config["pass_k"] + 1):
                if attempt_number > 1 and config["attempt_delay"] > 0:
                    time.sleep(config["attempt_delay"])
                result = run_pipeline(
                    raw_input=raw_claim or theorem_to_prove,
                    preformalized_theorem=theorem_to_prove,
                    use_cache=False,
                )
                attempts.append(result)
                if result.get("success"):
                    break
        elif evaluation_stage == "formalization":
            skipped_proving_reason = "stage_formalization_only"
        elif not formalization["success"]:
            skipped_proving_reason = "formalization_failed"
    except Exception as exc:
        runner_error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        semantic_grade = _semantic_placeholder(
            "runner_error",
            f"Evaluation case failed before completion: {exc}",
        )

    pass_at_k_success = any(attempt.get("success") for attempt in attempts)
    trace_metrics = aggregate_trace_metrics(attempts)
    expectation_met = _expectation_met(
        expected_outcome=expected_outcome,
        formalization=formalization,
        pass_at_k_success=pass_at_k_success,
        runner_error=runner_error,
    )

    return {
        "claim_id": claim_id,
        "raw_claim": raw_claim,
        "tags": claim.get("tags", []),
        "notes": claim.get("notes"),
        "expected_outcome": expected_outcome,
        "evaluation_stage": evaluation_stage,
        "formalization": formalization,
        "attempts": attempts,
        "attempt_count": len(attempts),
        "pass_at_k_success": pass_at_k_success,
        "trace_metrics": trace_metrics,
        "semantic_grade": semantic_grade,
        "runner_error": runner_error,
        "handled_gracefully": runner_error is None,
        "expectation_met": expectation_met,
        "outcome": _case_outcome(
            evaluation_stage=evaluation_stage,
            formalization=formalization,
            pass_at_k_success=pass_at_k_success,
            runner_error=runner_error,
        ),
        "skipped_proving_reason": skipped_proving_reason,
    }


def _semantic_summary(case_records: list[dict[str, Any]]) -> dict[str, Any]:
    numeric_scores = [
        int(record["semantic_grade"]["score"])
        for record in case_records
        if isinstance(record.get("semantic_grade", {}).get("score"), int)
    ]
    distribution = Counter(numeric_scores)
    average_score = 0.0
    if numeric_scores:
        average_score = sum(numeric_scores) / len(numeric_scores)
    return {
        "graded_cases": len(numeric_scores),
        "average_score": round(average_score, 3),
        "score_distribution": dict(sorted(distribution.items())),
    }


def _top_errors(metrics: dict[str, Any], limit: int = 5) -> list[str]:
    frequency = metrics.get("error_frequency", {})
    if not isinstance(frequency, dict):
        return []
    items = list(frequency.items())[:limit]
    return [f"{count}x {message}" for message, count in items]


def _expectation_summary(case_records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    labeled_records = [record for record in case_records if record.get("expected_outcome")]
    total_labeled = len(labeled_records)
    total_met = sum(1 for record in labeled_records if record.get("expectation_met") is True)

    for expectation in sorted(EXPECTATION_VALUES):
        relevant = [
            record for record in case_records if record.get("expected_outcome") == expectation
        ]
        if not relevant:
            continue
        met = sum(1 for record in relevant if record.get("expectation_met") is True)
        summary[expectation] = {
            "cases": len(relevant),
            "met": met,
            "rate": round(met / len(relevant), 3),
        }

    summary["labeled_cases"] = total_labeled
    summary["overall_met"] = total_met
    summary["overall_rate"] = round(total_met / total_labeled, 3) if total_labeled else 0.0
    return summary


def _build_summary(
    *,
    case_records: list[dict[str, Any]],
    config: dict[str, Any],
    aggregate_trace_metrics_result: dict[str, Any],
) -> dict[str, Any]:
    total_claims = len(case_records)
    formalization_cases = [
        record for record in case_records if record["evaluation_stage"] in {"formalization", "e2e"}
    ]
    proof_stage_cases = [
        record for record in case_records if record["evaluation_stage"] in {"prove", "e2e"}
    ]

    formalization_successes = sum(
        1 for record in formalization_cases if record["formalization"]["success"]
    )
    verified_cases = sum(1 for record in proof_stage_cases if record["pass_at_k_success"])
    unexpected_runner_failures = sum(
        1 for record in case_records if record["runner_error"] is not None
    )
    semantic_summary = _semantic_summary(case_records)
    expectation_summary = _expectation_summary(case_records)

    return {
        "total_claims": total_claims,
        "profile": config["profile"],
        "stage_mode": config["stage_mode"],
        "pass_k": config["pass_k"],
        "attempt_delay": config["attempt_delay"],
        "semantic_grading": config["semantic_grading"],
        "formalization_cases": len(formalization_cases),
        "formalization_successes": formalization_successes,
        "formalization_robustness": round(
            formalization_successes / len(formalization_cases),
            3,
        )
        if formalization_cases
        else 0.0,
        "proof_stage_cases": len(proof_stage_cases),
        "verified_cases": verified_cases,
        "agentic_proving_power": round(verified_cases / len(proof_stage_cases), 3)
        if proof_stage_cases
        else 0.0,
        "semantic_alignment_average": semantic_summary["average_score"],
        "semantic_alignment_graded_cases": semantic_summary["graded_cases"],
        "semantic_alignment_distribution": semantic_summary["score_distribution"],
        "unexpected_runner_failures": unexpected_runner_failures,
        "stage_counts": dict(
            sorted(Counter(record["evaluation_stage"] for record in case_records).items())
        ),
        "outcome_counts": dict(
            sorted(Counter(record["outcome"] for record in case_records).items())
        ),
        "expectation_summary": expectation_summary,
        "aggregate_trace_metrics": aggregate_trace_metrics_result,
    }


def _render_report(
    *,
    source_path: Path,
    overall_summary: dict[str, Any],
    aggregate_trace_metrics_result: dict[str, Any],
    case_records: list[dict[str, Any]],
) -> str:
    expectation_summary = overall_summary["expectation_summary"]
    lines = [
        "# Claim Evaluation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Input JSONL: `{source_path}`",
        f"Profile: `{overall_summary['profile']}`",
        f"Stage mode: `{overall_summary['stage_mode']}`",
        f"Configured pass@k: `{overall_summary['pass_k']}`",
        f"Semantic grading: `{overall_summary['semantic_grading']}`",
        "",
        "## Summary",
        "",
        f"- Total claims: {overall_summary['total_claims']}",
        (
            "- Formalization Robustness: "
            f"{overall_summary['formalization_robustness']:.3f} "
            f"({overall_summary['formalization_successes']}/"
            f"{overall_summary['formalization_cases']} formalization-stage cases)"
        ),
        (
            "- Agentic Proving Power: "
            f"{overall_summary['agentic_proving_power']:.3f} "
            f"({overall_summary['verified_cases']}/"
            f"{overall_summary['proof_stage_cases']} proof-stage cases)"
        ),
        (
            "- Expectation Benchmark Score: "
            f"{expectation_summary['overall_rate']:.3f} "
            f"({expectation_summary['overall_met']}/"
            f"{expectation_summary['labeled_cases']} labeled cases)"
        ),
        (
            "- Semantic Alignment average: "
            f"{overall_summary['semantic_alignment_average']:.3f} "
            f"across {overall_summary['semantic_alignment_graded_cases']} graded claims"
        ),
        (
            "- Tool Call Efficiency: "
            f"{aggregate_trace_metrics_result['tool_call_efficiency']:.3f} "
            f"({aggregate_trace_metrics_result['successful_tactic_applications']}/"
            f"{aggregate_trace_metrics_result['total_tool_calls']})"
        ),
        (f"- Tool Call Waste Ratio: {aggregate_trace_metrics_result['tool_call_waste_ratio']:.3f}"),
        (f"- Average Tactic Depth: {aggregate_trace_metrics_result['tactic_depth_average']:.3f}"),
        f"- Unexpected runner failures: {overall_summary['unexpected_runner_failures']}",
        (
            "- Stage mix: "
            + ", ".join(
                f"{stage}={count}" for stage, count in overall_summary["stage_counts"].items()
            )
        ),
        (
            "- Outcome mix: "
            + ", ".join(
                f"{outcome}={count}" for outcome, count in overall_summary["outcome_counts"].items()
            )
        ),
        "",
        "## Expectation Summary",
        "",
    ]

    expectation_lines = [
        key
        for key in sorted(expectation_summary)
        if key in EXPECTATION_VALUES and isinstance(expectation_summary.get(key), dict)
    ]
    if not expectation_lines:
        lines.append("- No labeled expectations in this dataset.")
    else:
        for key in expectation_lines:
            item = expectation_summary[key]
            lines.append(f"- `{key}`: {item['rate']:.3f} ({item['met']}/{item['cases']})")

    lines.extend(
        [
            "",
            "## Global Error Frequency",
            "",
        ]
    )

    top_global_errors = _top_errors(aggregate_trace_metrics_result, limit=10)
    if not top_global_errors:
        lines.append("- (none)")
    else:
        for error_line in top_global_errors:
            lines.append(f"- {error_line}")

    for record in case_records:
        formalization = record["formalization"]
        attempts = record["attempts"]
        trace_metrics = record["trace_metrics"]
        semantic_grade = record["semantic_grade"]
        lines.extend(
            [
                "",
                f"## {record['claim_id']}",
                "",
                f"- Stage: {record['evaluation_stage']}",
                f"- Expected outcome: {record.get('expected_outcome') or '(unlabeled)'}",
                f"- Expectation met: {record.get('expectation_met')}",
                f"- Outcome: {record['outcome']}",
                f"- Tags: {', '.join(record.get('tags', [])) if record.get('tags') else '(none)'}",
                f"- Formalization success: {formalization['success']}",
                f"- Formalization attempts: {formalization.get('attempts', 0)}",
                f"- pass@{overall_summary['pass_k']} success: {record['pass_at_k_success']}",
                f"- Attempts run: {len(attempts)}",
                f"- Semantic score: {semantic_grade.get('score')}",
                f"- Semantic verdict: {semantic_grade.get('verdict')}",
                f"- Tool Call Efficiency: {trace_metrics['tool_call_efficiency']:.3f}",
                f"- Tool Call Waste Ratio: {trace_metrics['tool_call_waste_ratio']:.3f}",
                f"- Average Tactic Depth: {trace_metrics['tactic_depth_average']:.3f}",
            ]
        )
        if record.get("skipped_proving_reason"):
            lines.append(f"- Proving skipped: {record['skipped_proving_reason']}")
        if record.get("runner_error"):
            lines.append(
                "- Runner error: "
                f"{record['runner_error']['type']}: {record['runner_error']['message']}"
            )
        top_case_errors = _top_errors(trace_metrics, limit=5)
        if top_case_errors:
            lines.append(f"- Top errors: {'; '.join(top_case_errors)}")
        if semantic_grade.get("trivialization_flags"):
            lines.append(
                f"- Trivialization flags: {', '.join(semantic_grade['trivialization_flags'])}"
            )
        if semantic_grade.get("rationale"):
            lines.extend(
                [
                    "",
                    "### Semantic Rationale",
                    "",
                    semantic_grade["rationale"],
                ]
            )
        if formalization.get("errors"):
            lines.extend(
                [
                    "",
                    "### Formalization Errors",
                    "",
                    "```text",
                    "\n".join(formalization["errors"][:5]),
                    "```",
                ]
            )

    return "\n".join(lines) + "\n"


def main() -> int:
    args = _parse_args()
    if not os.environ.get("MISTRAL_API_KEY"):
        print("MISTRAL_API_KEY is required to run claim evaluations.", file=sys.stderr)
        return 1

    source_path = Path(args.claims_jsonl).resolve()
    claims = _load_claims(source_path)
    if args.limit is not None:
        claims = claims[: args.limit]

    config = _resolve_config(args)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = Path(args.output_dir).resolve() / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)

    case_records_path = artifact_dir / "case_records.jsonl"
    results_path = artifact_dir / "results.json"
    report_path = artifact_dir / "report.md"

    case_records: list[dict[str, Any]] = []
    all_attempt_results: list[dict[str, Any]] = []

    with case_records_path.open("w", encoding="utf-8") as case_stream:
        for index, claim in enumerate(claims, start=1):
            case_record = _evaluate_case(
                claim=claim,
                index=index,
                config=config,
            )
            case_records.append(case_record)
            all_attempt_results.extend(case_record["attempts"])
            case_stream.write(json.dumps(case_record, ensure_ascii=False, default=str) + "\n")
            print(
                f"[{index}/{len(claims)}] {case_record['claim_id']}: "
                f"stage={case_record['evaluation_stage']} outcome={case_record['outcome']}"
            )

    aggregate_trace_metrics_result = aggregate_trace_metrics(all_attempt_results)
    overall_summary = _build_summary(
        case_records=case_records,
        config=config,
        aggregate_trace_metrics_result=aggregate_trace_metrics_result,
    )

    results_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_jsonl": str(source_path),
        "config": config,
        "summary": overall_summary,
        "aggregate_trace_metrics": aggregate_trace_metrics_result,
        "case_records": case_records,
    }

    results_path.write_text(
        json.dumps(results_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    report_path.write_text(
        _render_report(
            source_path=source_path,
            overall_summary=overall_summary,
            aggregate_trace_metrics_result=aggregate_trace_metrics_result,
            case_records=case_records,
        ),
        encoding="utf-8",
    )

    print(f"Wrote per-case JSONL to {case_records_path}")
    print(f"Wrote raw results to {results_path}")
    print(f"Wrote markdown report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
