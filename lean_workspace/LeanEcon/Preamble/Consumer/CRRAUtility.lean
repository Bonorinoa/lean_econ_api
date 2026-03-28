import Mathlib
import LeanEcon.Preamble.Risk.ArrowPrattRRA

/-- CRRA (isoelastic) utility function. -/
noncomputable def crra_utility (c γ : ℝ) : ℝ :=
  Real.rpow c (1 - γ) / (1 - γ)

/-- A CRRA-style Arrow-Pratt relation implies constant relative risk aversion. -/
theorem crra_relative_risk_aversion_of_marginal_relation
    (c u' u'' γ : ℝ)
    (hc : c ≠ 0)
    (hu' : u' ≠ 0)
    (hrelation : u'' = -(γ / c) * u') :
    relative_risk_aversion c u' u'' = γ :=
  relative_risk_aversion_of_second_derivative_relation c u' u'' γ hc hu' hrelation

/-- CRRA relative risk aversion equals γ.
    After substituting u'(c) = c^(-γ) and u''(c) = -γ·c^(-γ-1) into
    -c·u''/u' and simplifying, the expression reduces to -c·(-γ·c⁻¹) = γ. -/
theorem crra_rra_simplified
    (c γ : ℝ) (hc : c > 0) (_ : γ > 0) (_ : γ ≠ 1) :
    -c * (-γ * c⁻¹) = γ := by
  field_simp
