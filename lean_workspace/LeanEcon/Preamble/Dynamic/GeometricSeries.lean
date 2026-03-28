import Mathlib

/-- Geometric series partial sum. -/
noncomputable def geometric_partial_sum (a r : ℝ) (n : ℕ) : ℝ :=
  a * (1 - r ^ n) / (1 - r)

/-- The geometric-series partial sum is zero at horizon zero. -/
theorem geometric_partial_sum_zero
    (a r : ℝ) :
    geometric_partial_sum a r 0 = 0 := by
  simp [geometric_partial_sum]

/-- Extending the horizon by one period adds the next discounted payoff. -/
theorem geometric_partial_sum_succ
    (a r : ℝ) (n : ℕ)
    (hr : r ≠ 1) :
    geometric_partial_sum a r n.succ = geometric_partial_sum a r n + a * r ^ n := by
  unfold geometric_partial_sum
  rw [pow_succ]
  have hsplit : 1 - r ^ n * r = (1 - r ^ n) + (1 - r) * r ^ n := by
    ring
  rw [hsplit]
  have hden : 1 - r ≠ 0 := sub_ne_zero.mpr hr.symm
  field_simp [hden]
