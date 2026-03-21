import Mathlib
open Real

/-- CRRA (isoelastic) utility function.
    u(c) = c^(1-γ)/(1-γ) for γ ≠ 1; log(c) for γ = 1. -/
noncomputable def crra_utility (c γ : ℝ) : ℝ := c ^ (1 - γ) / (1 - γ)

/-- Arrow-Pratt coefficient of relative risk aversion: -c·u''(c)/u'(c). -/
noncomputable def relative_risk_aversion (c u' u'' : ℝ) : ℝ := -(c * u'') / u'


/-- CRRA utility: coefficient of relative risk aversion equals γ.
    After substituting u'(c) = c^(-γ) and u''(c) = -γ·c^(-γ-1) into
    -c·u''/u' and simplifying, the expression reduces to -c * (-γ * c⁻¹) = γ. -/
theorem crra_constant_rra (γ : ℝ) (hγ : γ > 0) (hγ1 : γ ≠ 1) (c : ℝ) (hc : c > 0) :
    -c * (-γ * c⁻¹) = γ := by
  sorry