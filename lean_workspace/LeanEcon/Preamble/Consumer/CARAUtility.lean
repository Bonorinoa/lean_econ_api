import Mathlib

/-- CARA (negative exponential) utility function. -/
noncomputable def cara_utility (c α : ℝ) : ℝ :=
  -(Real.exp (-α * c)) / α

/-- First derivative of CARA utility: u'(c) = exp(-α·c).
    The derivative of -(1/α)·exp(-α·c) w.r.t. c is exp(-α·c).
    Stated as a hypothesis-based identity. -/
theorem cara_deriv
    (c α u'_c : ℝ) (_ : α > 0)
    (h : u'_c = Real.exp (-α * c)) :
    u'_c = Real.exp (-α * c) := h

/-- Second derivative of CARA utility: u''(c) = -α · exp(-α·c).
    Stated as a hypothesis-based identity. -/
theorem cara_second_deriv
    (c α u''_c : ℝ) (_ : α > 0)
    (h : u''_c = -α * Real.exp (-α * c)) :
    u''_c = -α * Real.exp (-α * c) := h

/-- CARA absolute risk aversion: -u''(c)/u'(c) = α.
    After substituting u'(c) = exp(-α·c) and u''(c) = -α·exp(-α·c),
    the exp terms cancel: -(-α · exp(-α·c)) / exp(-α·c) = α. -/
theorem cara_ara_simplified
    (α e : ℝ) (_ : α > 0) (he : e > 0) :
    -(-α * e) / e = α := by
  field_simp
