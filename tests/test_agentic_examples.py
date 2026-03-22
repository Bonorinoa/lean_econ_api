"""
Lightweight raw-Lean regression checks for the agentic prover.

Usage:
  pytest -m live tests/test_agentic_examples.py
  python tests/test_agentic_examples.py
"""

from __future__ import annotations

import time

import pytest

from pipeline import prove_and_verify

ONE_PLUS_ONE_THEOREM = """\
import Mathlib
open Real

theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""

CRRA_RAW_THEOREM = """\
import Mathlib
open Real

theorem crra_rra (γ : ℝ) (hγ : γ > 0) (c : ℝ) (hc : c > 0) :
    -c * (-γ * c⁻¹) = γ := by
  sorry
"""

COBB_RAW_SIMPLIFIED_THEOREM = """\
import Mathlib
open Real

theorem cobb_douglas_elasticity_capital (α K : ℝ) (hα : 0 < α) (hα1 : α < 1)
    (hK : K > 0) :
    α * K * K⁻¹ = α := by
  sorry
"""


@pytest.mark.live
def test_one_plus_one_agentic() -> None:
    result = prove_and_verify(ONE_PLUS_ONE_THEOREM)
    assert result["success"]


@pytest.mark.live
def test_crra_raw_agentic() -> None:
    result = prove_and_verify(CRRA_RAW_THEOREM)
    assert result["success"]


@pytest.mark.live
def test_cobb_raw_agentic() -> None:
    result = prove_and_verify(COBB_RAW_SIMPLIFIED_THEOREM)
    assert result["success"]


# ---------------------------------------------------------------------------
# Standalone runner (fallback)
# ---------------------------------------------------------------------------

def _run_case(name: str, theorem_with_sorry: str) -> bool:
    start = time.time()
    result = prove_and_verify(theorem_with_sorry)
    elapsed = time.time() - start
    status = "PASS" if result["success"] else "FAIL"
    preview_errors = result["errors"][:2]

    print(f"\n{name}")
    print(f"  status:        {status}")
    print(f"  attempts_used: {result['attempts_used']}")
    print(f"  proof_tactics: {result['proof_tactics']}")
    print(f"  elapsed:       {elapsed:.1f}s")
    if preview_errors:
        print(f"  errors:        {preview_errors}")

    return result["success"]


def main() -> int:
    print("=" * 60)
    print("LeanEcon Agentic Raw-Lean Regression Checks")
    print("=" * 60)

    results = {
        "one_plus_one_agentic": _run_case("1 + 1 = 2", ONE_PLUS_ONE_THEOREM),
        "crra_raw_agentic": _run_case("CRRA raw Lean", CRRA_RAW_THEOREM),
        "cobb_raw_agentic": _run_case(
            "Simplified Cobb-Douglas raw Lean",
            COBB_RAW_SIMPLIFIED_THEOREM,
        ),
    }

    print("\n" + "=" * 60)
    print("Results:")
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
