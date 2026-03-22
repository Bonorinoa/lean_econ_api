"""
Lightweight raw-Lean regression checks for the agentic prover.

Usage:
  pytest -m live tests/test_agentic_examples.py
"""

from __future__ import annotations

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
