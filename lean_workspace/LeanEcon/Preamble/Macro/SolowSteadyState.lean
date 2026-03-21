import Mathlib

/-- Solow model steady-state capital per effective worker.
    At steady state: s * A * k^α = (n + g + δ) * k. -/
noncomputable def solow_investment (s A k α : ℝ) : ℝ :=
  s * A * Real.rpow k α

noncomputable def solow_depreciation (n g δ k : ℝ) : ℝ :=
  (n + g + δ) * k

/-- Solow steady-state condition: investment equals effective depreciation. -/
theorem solow_steady_state
    (s A k α n g δ : ℝ)
    (h : s * A * Real.rpow k α = (n + g + δ) * k) :
    solow_investment s A k α = solow_depreciation n g δ k := h
