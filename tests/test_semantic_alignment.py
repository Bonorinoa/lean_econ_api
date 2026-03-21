"""Regression checks for semantic-alignment grading helpers."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import semantic_alignment


def _run_case(name: str, fn) -> bool:
    try:
        fn()
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False
    print(f"{name}: PASS")
    return True


def _test_grade_semantic_alignment_success() -> None:
    response = """\
```json
{"score": 4, "verdict": "mostly_faithful", "rationale": "Close match.", "trivialization_flags": ["minor_simplification"]}
```"""
    with patch.object(semantic_alignment, "call_leanstral", return_value=response):
        result = semantic_alignment.grade_semantic_alignment("claim", "theorem one : True := by trivial")
    assert result["generated"] is True
    assert result["score"] == 4
    assert result["verdict"] == "mostly_faithful"
    assert result["trivialization_flags"] == ["minor_simplification"]


def _test_grade_semantic_alignment_failure_fallback() -> None:
    with patch.object(semantic_alignment, "call_leanstral", side_effect=RuntimeError("api down")):
        result = semantic_alignment.grade_semantic_alignment("claim", "theorem one : True := by trivial")
    assert result["generated"] is False
    assert result["score"] is None
    assert result["verdict"] == "grading_error"
    assert "api down" in result["rationale"]


def main() -> int:
    print("=" * 60)
    print("LeanEcon Semantic Alignment Tests")
    print("=" * 60)

    results = {
        "grade_semantic_alignment_success": _run_case(
            "grade_semantic_alignment_success",
            _test_grade_semantic_alignment_success,
        ),
        "grade_semantic_alignment_failure_fallback": _run_case(
            "grade_semantic_alignment_failure_fallback",
            _test_grade_semantic_alignment_failure_fallback,
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
