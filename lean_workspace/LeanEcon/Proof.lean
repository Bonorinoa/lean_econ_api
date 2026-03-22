import Mathlib
open Real

/-- For all real c > 0 and γ > 0 with γ ≠ 1, -c * (-γ * c⁻¹) = γ. -/
theorem algebraic_identity (c γ : ℝ) (hc : 0 < c) (hγ : 0 < γ) (hγ1 : γ ≠ 1) :
  -c * (-γ * c⁻¹) = γ := by
  sorry