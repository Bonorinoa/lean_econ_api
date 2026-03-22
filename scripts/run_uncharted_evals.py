"""Run advanced evaluation cases while bypassing the classifier stage."""

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

from eval_metrics import aggregate_trace_metrics
from pipeline import formalize_claim, run_pipeline
from semantic_alignment import grade_semantic_alignment

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "uncharted_evals"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LeanEcon uncharted evaluations.")
    parser.add_argument("claims_jsonl", help="JSONL file of advanced claims to evaluate.")
    parser.add_argument(
        "--pass-k",
        type=int,
        default=5,
        help="Maximum number of proving attempts per formalized claim.",
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
        default=5,
        help="Seconds to wait between pass@k proving attempts (default: 5).",
    )
    return parser.parse_args()


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
        if not isinstance(raw_claim, str) or not raw_claim.strip():
            raise ValueError(f"Line {line_number} is missing a non-empty `raw_claim`.")
        claims.append(payload)
    return claims


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


def _render_report(
    *,
    source_path: Path,
    pass_k: int,
    overall_summary: dict[str, Any],
    aggregate_trace_metrics_result: dict[str, Any],
    case_records: list[dict[str, Any]],
) -> str:
    lines = [
        "# Uncharted Evaluation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Input JSONL: `{source_path}`",
        f"Configured pass@k: `{pass_k}`",
        "",
        "## Summary",
        "",
        f"- Total claims: {overall_summary['total_claims']}",
        (
            "- Formalization Robustness: "
            f"{overall_summary['formalization_robustness']:.3f} "
            f"({overall_summary['formalization_successes']}/{overall_summary['total_claims']})"
        ),
        (
            "- Agentic Proving Power (pass@k verified rate): "
            f"{overall_summary['agentic_proving_power']:.3f} "
            f"({overall_summary['verified_cases']}/{overall_summary['total_claims']})"
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
        (
            "- Average Tactic Depth: "
            f"{aggregate_trace_metrics_result['tactic_depth_average']:.3f}"
        ),
        "",
        "## Global Error Frequency",
        "",
    ]

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
                f"- Tags: {', '.join(record.get('tags', [])) if record.get('tags') else '(none)'}",
                f"- Formalization success: {formalization['success']}",
                f"- Formalization attempts: {formalization.get('attempts', 0)}",
                f"- pass@{pass_k} success: {record['pass_at_k_success']}",
                f"- Attempts run: {len(attempts)}",
                f"- Semantic score: {semantic_grade.get('score')}",
                f"- Semantic verdict: {semantic_grade.get('verdict')}",
                f"- Tool Call Efficiency: {trace_metrics['tool_call_efficiency']:.3f}",
                f"- Average Tactic Depth: {trace_metrics['tactic_depth_average']:.3f}",
            ]
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
        print("MISTRAL_API_KEY is required to run uncharted evaluations.", file=sys.stderr)
        return 1

    source_path = Path(args.claims_jsonl).resolve()
    claims = _load_claims(source_path)
    if args.limit is not None:
        claims = claims[: args.limit]

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_dir = Path(args.output_dir).resolve() / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)

    case_records: list[dict[str, Any]] = []
    all_attempt_results: list[dict[str, Any]] = []

    for index, claim in enumerate(claims, start=1):
        claim_id = str(claim.get("id") or f"claim_{index:03d}")
        raw_claim = str(claim["raw_claim"])
        preamble_names = claim.get("preamble_names")
        if not isinstance(preamble_names, list):
            preamble_names = None

        formalization = formalize_claim(
            raw_claim,
            preamble_names=preamble_names,
        )

        if formalization["success"]:
            semantic_grade = grade_semantic_alignment(raw_claim, formalization["theorem_code"])
        else:
            semantic_grade = {
                "score": None,
                "verdict": "formalization_failed",
                "rationale": "Semantic grading skipped because formalization failed.",
                "trivialization_flags": [],
                "generated": False,
            }

        attempts: list[dict[str, Any]] = []
        if formalization["success"]:
            for _attempt in range(1, args.pass_k + 1):
                if _attempt > 1 and args.attempt_delay > 0:
                    time.sleep(args.attempt_delay)
                result = run_pipeline(
                    raw_input=raw_claim,
                    preformalized_theorem=formalization["theorem_code"],
                    use_cache=False,
                )
                attempts.append(result)
                all_attempt_results.append(result)
                if result.get("success"):
                    break

        trace_metrics_result = aggregate_trace_metrics(attempts)
        pass_at_k_success = any(attempt.get("success") for attempt in attempts)

        case_records.append(
            {
                "claim_id": claim_id,
                "raw_claim": raw_claim,
                "tags": claim.get("tags", []),
                "notes": claim.get("notes"),
                "formalization": formalization,
                "attempts": attempts,
                "attempt_count": len(attempts),
                "pass_at_k_success": pass_at_k_success,
                "trace_metrics": trace_metrics_result,
                "semantic_grade": semantic_grade,
            }
        )

    formalization_successes = sum(1 for record in case_records if record["formalization"]["success"])
    verified_cases = sum(1 for record in case_records if record["pass_at_k_success"])
    semantic_summary = _semantic_summary(case_records)
    aggregate_trace_metrics_result = aggregate_trace_metrics(all_attempt_results)

    total_claims = len(case_records)
    overall_summary = {
        "total_claims": total_claims,
        "formalization_successes": formalization_successes,
        "formalization_robustness": round(
            formalization_successes / total_claims,
            3,
        )
        if total_claims
        else 0.0,
        "verified_cases": verified_cases,
        "agentic_proving_power": round(verified_cases / total_claims, 3) if total_claims else 0.0,
        "semantic_alignment_average": semantic_summary["average_score"],
        "semantic_alignment_graded_cases": semantic_summary["graded_cases"],
        "semantic_alignment_distribution": semantic_summary["score_distribution"],
    }

    results_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_jsonl": str(source_path),
        "pass_k": args.pass_k,
        "summary": overall_summary,
        "aggregate_trace_metrics": aggregate_trace_metrics_result,
        "case_records": case_records,
    }

    results_path = artifact_dir / "results.json"
    report_path = artifact_dir / "report.md"
    results_path.write_text(
        json.dumps(results_payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    report_path.write_text(
        _render_report(
            source_path=source_path,
            pass_k=args.pass_k,
            overall_summary=overall_summary,
            aggregate_trace_metrics_result=aggregate_trace_metrics_result,
            case_records=case_records,
        ),
        encoding="utf-8",
    )

    print(f"Wrote raw results to {results_path}")
    print(f"Wrote markdown report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
