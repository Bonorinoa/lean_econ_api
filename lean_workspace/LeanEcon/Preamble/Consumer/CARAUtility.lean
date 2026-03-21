import Mathlib

/-- CARA (negative exponential) utility function. -/
noncomputable def cara_utility (c α : ℝ) : ℝ :=
  -(Real.exp (-α * c)) / α
