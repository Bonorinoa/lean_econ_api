import Mathlib
open Real

/-- CRRA utility: coefficient of relative risk aversion equals γ.
    We express this as the algebraic identity obtained after substituting
    u'(c) = c^(-γ) and u''(c) = -γ·c^(-γ-1) into -c·u''/u'. -/
theorem crra_rra (γ : ℝ) (hγ : γ > 0) (hγ1 : γ ≠ 1) (c : ℝ) (hc : c > 0) :
    -c * (-γ * c⁻¹) = γ := by
  field_simp [ne_of_gt hc]
    ring
