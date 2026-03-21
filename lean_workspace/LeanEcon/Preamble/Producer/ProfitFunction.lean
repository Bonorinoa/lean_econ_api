import Mathlib

/-- Profit function for a single-input firm. -/
noncomputable def profit (p w A α : ℝ) (x_star : ℝ) : ℝ :=
  p * (A * Real.rpow x_star α) - w * x_star

/-- First-order condition for profit maximization:
    p · ∂(A·x^α)/∂x = w, i.e., p · α · A · x^(α-1) = w.
    Stated as a hypothesis-based identity. -/
theorem profit_foc
    (p w A α x_star : ℝ) (_ : p > 0) (_ : A > 0) (_ : x_star > 0)
    (h : p * (α * A * Real.rpow x_star (α - 1)) = w) :
    p * (α * A * Real.rpow x_star (α - 1)) = w := h
