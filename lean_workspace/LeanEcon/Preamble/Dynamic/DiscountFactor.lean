import Mathlib

/-- Present value with geometric discounting for a constant stream. -/
noncomputable def present_value_constant (x β : ℝ) (T : ℕ) : ℝ :=
  x * (1 - β ^ T) / (1 - β)
