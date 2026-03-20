import Mathlib

/-- Doubling any natural number produces an even number. -/
theorem double_is_even (n : ℕ) :
    Even (2 * n) := by
  simpa [two_mul] using (show Even (n + n) from ⟨n, rfl⟩)
