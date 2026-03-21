"""Regression checks for trace-analysis helpers."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from eval_metrics import aggregate_trace_metrics, extract_tactic_heads, load_jsonl_records


def _run_case(name: str, fn) -> bool:
    try:
        fn()
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False
    print(f"{name}: PASS")
    return True


def _test_load_jsonl_records_tolerates_malformed_lines() -> None:
    entries = [
        json.dumps({"verification": {"success": True}}),
        "{bad json",
        json.dumps({"verification": {"success": False}}),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "runs.jsonl"
        path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        records, malformed = load_jsonl_records(path)
    assert len(records) == 2
    assert malformed == 1


def _test_extract_tactic_heads() -> None:
    tactic_block = """\
constructor
· exact h1
· simp
"""
    assert extract_tactic_heads(tactic_block) == ["constructor", "exact", "simp"]


def _test_aggregate_trace_metrics() -> None:
    records = [
        {
            "success": True,
            "proof_tactics": "constructor\n· exact h\n· simp",
            "tool_trace": [
                {"type": "tool_call", "tool_name": "apply_tactic"},
                {"type": "tool_call", "tool_name": "lean_diagnostic_messages"},
            ],
            "tactic_calls": [
                {"tactic": "constructor\n· exact h\n· simp", "successful": True},
            ],
        },
        {
            "success": False,
            "tool_trace": [
                {
                    "type": "tool_call",
                    "tool_name": "lean_diagnostic_messages",
                    "kernel_errors": ["line 7: unknown identifier x"],
                }
            ],
            "tactic_calls": [
                {"tactic": "exact x", "successful": False},
            ],
            "errors": ["line 7: unknown identifier x"],
        },
    ]
    metrics = aggregate_trace_metrics(records)
    assert metrics["runs_considered"] == 2
    assert metrics["total_tool_calls"] == 3
    assert metrics["successful_tactic_applications"] == 1
    assert metrics["tool_call_efficiency"] == 0.333
    assert metrics["tactic_depth_average"] == 3.0
    assert metrics["error_frequency"]["line 7: unknown identifier x"] == 1


def main() -> int:
    print("=" * 60)
    print("LeanEcon Eval Metrics Tests")
    print("=" * 60)

    results = {
        "load_jsonl_records_tolerates_malformed_lines": _run_case(
            "load_jsonl_records_tolerates_malformed_lines",
            _test_load_jsonl_records_tolerates_malformed_lines,
        ),
        "extract_tactic_heads": _run_case(
            "extract_tactic_heads",
            _test_extract_tactic_heads,
        ),
        "aggregate_trace_metrics": _run_case(
            "aggregate_trace_metrics",
            _test_aggregate_trace_metrics,
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
