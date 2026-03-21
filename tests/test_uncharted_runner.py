"""Regression checks for the uncharted evaluation runner."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import run_uncharted_evals


def _run_case(name: str, fn) -> bool:
    try:
        fn()
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False
    print(f"{name}: PASS")
    return True


def _test_runner_writes_report_and_results() -> None:
    claims = [
        {"id": "dynamic_001", "raw_claim": "Bellman operator is a contraction.", "tags": ["dynamic"]},
        {"id": "dynamic_002", "raw_claim": "Value function exists.", "tags": ["dynamic"]},
    ]

    formalization_results = {
        "Bellman operator is a contraction.": {
            "success": True,
            "theorem_code": "theorem contraction : True := by sorry",
            "attempts": 1,
            "errors": [],
            "formalization_failed": False,
            "failure_reason": None,
        },
        "Value function exists.": {
            "success": False,
            "theorem_code": "",
            "attempts": 3,
            "errors": ["missing definitions"],
            "formalization_failed": True,
            "failure_reason": "Needs missing definitions.",
        },
    }
    pipeline_attempts = iter(
        [
            {
                "success": False,
                "proof_tactics": "simp",
                "tool_trace": [
                    {
                        "type": "tool_call",
                        "tool_name": "lean_diagnostic_messages",
                        "kernel_errors": ["line 5: tactic failed"],
                    }
                ],
                "tactic_calls": [{"tactic": "simp", "successful": False}],
            },
            {
                "success": True,
                "proof_tactics": "constructor\n· exact h\n· simp",
                "tool_trace": [
                    {"type": "tool_call", "tool_name": "apply_tactic"},
                    {"type": "tool_call", "tool_name": "lean_diagnostic_messages"},
                ],
                "tactic_calls": [{"tactic": "constructor\n· exact h\n· simp", "successful": True}],
            },
        ]
    )

    def fake_formalize_claim(raw_input: str, on_log=None, preamble_names=None):
        return formalization_results[raw_input]

    def fake_run_pipeline(*, raw_input: str, preformalized_theorem: str, use_cache: bool):
        return next(pipeline_attempts)

    def fake_grade_semantic_alignment(original_raw_claim: str, generated_theorem_code: str):
        return {
            "score": 4,
            "verdict": "mostly_faithful",
            "rationale": "Looks good.",
            "trivialization_flags": [],
            "generated": True,
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        claims_path = Path(tmpdir) / "claims.jsonl"
        output_dir = Path(tmpdir) / "outputs"
        claims_path.write_text(
            "\n".join(json.dumps(item) for item in claims) + "\n",
            encoding="utf-8",
        )

        argv = [
            "run_uncharted_evals.py",
            str(claims_path),
            "--pass-k",
            "3",
            "--output-dir",
            str(output_dir),
        ]
        with patch.object(run_uncharted_evals, "formalize_claim", side_effect=fake_formalize_claim), \
             patch.object(run_uncharted_evals, "run_pipeline", side_effect=fake_run_pipeline), \
             patch.object(run_uncharted_evals, "grade_semantic_alignment", side_effect=fake_grade_semantic_alignment), \
             patch.object(sys, "argv", argv), \
             patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}, clear=False):
            exit_code = run_uncharted_evals.main()

        assert exit_code == 0
        result_files = list(output_dir.glob("*/results.json"))
        report_files = list(output_dir.glob("*/report.md"))
        assert len(result_files) == 1
        assert len(report_files) == 1

        payload = json.loads(result_files[0].read_text(encoding="utf-8"))
        assert payload["summary"]["formalization_successes"] == 1
        assert payload["summary"]["verified_cases"] == 1
        assert payload["aggregate_trace_metrics"]["tool_call_efficiency"] == 0.333

        report_text = report_files[0].read_text(encoding="utf-8")
        assert "Uncharted Evaluation Report" in report_text
        assert "dynamic_001" in report_text
        assert "Formalization Robustness" in report_text


def main() -> int:
    print("=" * 60)
    print("LeanEcon Uncharted Runner Tests")
    print("=" * 60)

    results = {
        "runner_writes_report_and_results": _run_case(
            "runner_writes_report_and_results",
            _test_runner_writes_report_and_results,
        ),
    }

    print("\n" + "=" * 60)
    print("Results:")
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
