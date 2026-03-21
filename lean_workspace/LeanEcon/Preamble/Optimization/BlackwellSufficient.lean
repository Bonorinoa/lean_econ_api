import Mathlib

/-- Blackwell's monotonicity condition: if f ≤ g pointwise then T(f) ≤ T(g). -/
def blackwell_monotone (T : (ℝ → ℝ) → (ℝ → ℝ)) : Prop :=
  ∀ f g : ℝ → ℝ, (∀ x, f x ≤ g x) → ∀ x, T f x ≤ T g x

/-- Blackwell's discounting condition: T(f + c) ≤ T(f) + β * c for constant c ≥ 0. -/
def blackwell_discounting (T : (ℝ → ℝ) → (ℝ → ℝ)) (β : ℝ) : Prop :=
  ∀ f : ℝ → ℝ, ∀ c : ℝ, 0 ≤ c →
    ∀ x, T (fun y => f y + c) x ≤ T f x + β * c

/-- Blackwell's sufficient conditions: monotonicity and discounting with 0 ≤ β < 1
    imply the operator is a contraction. -/
def blackwell_sufficient (T : (ℝ → ℝ) → (ℝ → ℝ)) (β : ℝ) : Prop :=
  blackwell_monotone T ∧ blackwell_discounting T β ∧ 0 ≤ β ∧ β < 1
