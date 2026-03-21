import Mathlib
import LeanEcon.Preamble.Consumer.CRRAUtility
import LeanEcon.Preamble.Consumer.CARAUtility
import LeanEcon.Preamble.Risk.ArrowPrattRRA

open Real

/-- CRRA utility: coefficient of relative risk aversion equals γ.
    After substituting u'(c) = c^(-γ) and u''(c) = -γ·c^(-γ-1) into
    -c·u''/u' and simplifying, the expression reduces to -c·(-γ·c⁻¹) = γ. -/
theorem crra_constant_rra (γ : ℝ) (hγ : γ > 0) (hγ1 : γ ≠ 1) (c : ℝ) (hc : c > 0) :
    -c * (-γ * c⁻¹) = γ := by
  sorry
