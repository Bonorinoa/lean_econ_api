import Mathlib

/-- Two-factor Cobb-Douglas production function. -/
noncomputable def cobb_douglas (A K L α : ℝ) : ℝ :=
  A * Real.rpow K α * Real.rpow L (1 - α)
