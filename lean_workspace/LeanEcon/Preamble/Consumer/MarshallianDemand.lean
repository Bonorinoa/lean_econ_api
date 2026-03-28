import Mathlib

/-- Marshallian demand for good 1 in a two-good Cobb-Douglas economy. -/
noncomputable def marshallian_demand_good1 (α m p₁ : ℝ) : ℝ :=
  α * m / p₁

/-- Marshallian demand for good 2 in a two-good Cobb-Douglas economy. -/
noncomputable def marshallian_demand_good2 (α m p₂ : ℝ) : ℝ :=
  (1 - α) * m / p₂

/-- Spending on good 1 under Cobb-Douglas demand equals the `α` budget share. -/
theorem marshallian_spending_good1
    (α m p₁ : ℝ)
    (hp₁ : p₁ ≠ 0) :
    p₁ * marshallian_demand_good1 α m p₁ = α * m := by
  unfold marshallian_demand_good1
  field_simp [hp₁]

/-- Spending on good 2 under Cobb-Douglas demand equals the `1 - α` budget share. -/
theorem marshallian_spending_good2
    (α m p₂ : ℝ)
    (hp₂ : p₂ ≠ 0) :
    p₂ * marshallian_demand_good2 α m p₂ = (1 - α) * m := by
  unfold marshallian_demand_good2
  field_simp [hp₂]

/-- Two-good Cobb-Douglas Marshallian demand exhausts the budget. -/
theorem marshallian_budget_exhausted
    (α m p₁ p₂ : ℝ)
    (hp₁ : p₁ ≠ 0)
    (hp₂ : p₂ ≠ 0) :
    p₁ * marshallian_demand_good1 α m p₁ + p₂ * marshallian_demand_good2 α m p₂ = m := by
  unfold marshallian_demand_good1 marshallian_demand_good2
  field_simp [hp₁, hp₂]
  ring
