import Mathlib

/-- The sum of two even natural numbers is even. -/
theorem even_add_even (a b : ℕ) (ha : Even a) (hb : Even b) :
    Even (a + b) := by
  exact Even.add ha hb
