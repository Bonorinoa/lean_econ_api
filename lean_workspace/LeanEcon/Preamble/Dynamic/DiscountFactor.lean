import Mathlib
import LeanEcon.Preamble.Dynamic.GeometricSeries

/-- Present value with geometric discounting for a constant stream. -/
noncomputable def present_value_constant (x β : ℝ) (T : ℕ) : ℝ :=
  x * (1 - β ^ T) / (1 - β)

/-- Present value for a constant stream is exactly a geometric partial sum. -/
theorem present_value_constant_eq_geometric_partial_sum
    (x β : ℝ) (T : ℕ) :
    present_value_constant x β T = geometric_partial_sum x β T :=
  rfl

/-- Zero horizon implies zero present value. -/
theorem present_value_constant_zero_horizon
    (x β : ℝ) :
    present_value_constant x β 0 = 0 := by
  simp [present_value_constant]

/-- Adding one more discounted payoff extends present value by `x * β^T`. -/
theorem present_value_constant_succ
    (x β : ℝ) (T : ℕ)
    (hβ : β ≠ 1) :
    present_value_constant x β T.succ = present_value_constant x β T + x * β ^ T := by
  simpa [present_value_constant_eq_geometric_partial_sum] using
    geometric_partial_sum_succ x β T hβ
