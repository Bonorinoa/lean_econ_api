import Mathlib

/-- CRRA (isoelastic) utility function. -/
noncomputable def crra_utility (c γ : ℝ) : ℝ :=
  Real.rpow c (1 - γ) / (1 - γ)
