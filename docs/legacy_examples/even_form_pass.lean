import Mathlib

/-- Every even natural number can be written as `2 * n` for some natural number `n`. -/
theorem even_numbers_have_form_two_n (m : ℕ) (hm : Even m) :
    ∃ n : ℕ, m = 2 * n := by
  rcases hm with ⟨k, hk⟩
  use k
  simpa [two_mul] using hk
