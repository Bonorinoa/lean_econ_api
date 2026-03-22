"""
Standalone smoke tests for pipeline.py.

Usage:
  pytest tests/test_pipeline_smoke.py
  python tests/test_pipeline_smoke.py
"""

from __future__ import annotations

from pipeline import formalize_claim, parse_claim

RAW_LEAN_THEOREM = """\
import Mathlib
open Real

theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""


def test_parse_claim() -> None:
    raw_input = r"""
% A comment that should be removed
\begin{theorem}

Under CRRA utility, relative risk aversion is constant.

\end{theorem}
"""
    parsed = parse_claim(raw_input)
    expected = "Under CRRA utility, relative risk aversion is constant."
    assert parsed["text"] == expected, parsed["text"]


def test_raw_lean_bypass() -> None:
    result = formalize_claim(RAW_LEAN_THEOREM)
    assert result["success"] is True
    assert result["attempts"] == 0
    assert result["formalization_failed"] is False
    assert result["theorem_code"] == RAW_LEAN_THEOREM.strip()


# ---------------------------------------------------------------------------
# Standalone runner (fallback)
# ---------------------------------------------------------------------------

def _run_case(name: str, fn) -> bool:
    try:
        fn()
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False
    print(f"{name}: PASS")
    return True


def main() -> int:
    print("=" * 60)
    print("LeanEcon Pipeline Smoke Tests")
    print("=" * 60)

    results = {
        "parse_claim": _run_case("parse_claim", test_parse_claim),
        "raw_lean_bypass": _run_case("raw_lean_bypass", test_raw_lean_bypass),
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
