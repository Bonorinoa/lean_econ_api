import Mathlib
open Real

/-- A consumer who spends all income satisfies the budget equality. -/
theorem budget_constraint
    (m p₁ p₂ x₁ x₂ : ℝ)
    (hm : m > 0) (hp₁ : p₁ > 0) (hp₂ : p₂ > 0)
    (hspend : p₁ * x₁ + p₂ * x₂ = m) :
    p₁ * x₁ + p₂ * x₂ = m := by
  exact hspend
