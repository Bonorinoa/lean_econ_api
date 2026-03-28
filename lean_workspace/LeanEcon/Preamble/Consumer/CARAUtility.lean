import Mathlib
import LeanEcon.Preamble.Risk.ArrowPrattARA

/-- CARA (negative exponential) utility function. -/
noncomputable def cara_utility (c α : ℝ) : ℝ :=
  -(Real.exp (-α * c)) / α

/-- A CARA-style Arrow-Pratt relation implies constant absolute risk aversion. -/
theorem cara_absolute_risk_aversion_of_marginal_relation
    (u' u'' α : ℝ)
    (hu' : u' ≠ 0)
    (hrelation : u'' = -α * u') :
    absolute_risk_aversion u' u'' = α :=
  absolute_risk_aversion_of_second_derivative_relation u' u'' α hu' hrelation

/-- CARA absolute risk aversion: -u''(c)/u'(c) = α.
    After substituting u'(c) = exp(-α·c) and u''(c) = -α·exp(-α·c),
    the exp terms cancel: -(-α · exp(-α·c)) / exp(-α·c) = α. -/
theorem cara_ara_simplified
    (α e : ℝ) (_ : α > 0) (he : e > 0) :
    -(-α * e) / e = α := by
  field_simp
