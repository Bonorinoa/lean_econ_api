import Mathlib

/-- Budget set for two goods under a linear budget constraint. -/
def in_budget_set (p₁ p₂ m x₁ x₂ : ℝ) : Prop :=
  p₁ * x₁ + p₂ * x₂ ≤ m

/-- A bundle satisfying the budget inequality lies in the budget set. -/
theorem budget_set_membership
    (p₁ p₂ m x₁ x₂ : ℝ)
    (hbudget : p₁ * x₁ + p₂ * x₂ ≤ m) :
    in_budget_set p₁ p₂ m x₁ x₂ :=
  hbudget

/-- Membership in the two-good budget set is equivalent to the budget inequality. -/
theorem in_budget_set_iff
    (p₁ p₂ m x₁ x₂ : ℝ) :
    in_budget_set p₁ p₂ m x₁ x₂ ↔ p₁ * x₁ + p₂ * x₂ ≤ m :=
  Iff.rfl
