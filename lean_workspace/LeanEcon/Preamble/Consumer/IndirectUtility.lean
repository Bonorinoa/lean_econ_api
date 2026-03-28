import Mathlib

/-- Indirect utility for Cobb-Douglas preferences. -/
noncomputable def indirect_utility_cd (α p₁ p₂ m : ℝ) : ℝ :=
  Real.rpow (α / p₁) α * Real.rpow ((1 - α) / p₂) (1 - α) * m

/-- Cobb-Douglas indirect utility is zero at zero income. -/
theorem indirect_utility_cd_zero_income
    (α p₁ p₂ : ℝ) :
    indirect_utility_cd α p₁ p₂ 0 = 0 := by
  simp [indirect_utility_cd]

/-- Cobb-Douglas indirect utility is homogeneous of degree one in income. -/
theorem indirect_utility_cd_income_scaling
    (α p₁ p₂ t m : ℝ) :
    indirect_utility_cd α p₁ p₂ (t * m) = t * indirect_utility_cd α p₁ p₂ m := by
  unfold indirect_utility_cd
  ring
