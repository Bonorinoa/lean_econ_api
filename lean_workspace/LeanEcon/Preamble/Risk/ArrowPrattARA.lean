import Mathlib

/-- Arrow-Pratt coefficient of absolute risk aversion. -/
noncomputable def absolute_risk_aversion (u' u'' : ℝ) : ℝ :=
  -(u'') / u'

/-- If the second derivative equals `-α * u'`, then absolute risk aversion is `α`. -/
theorem absolute_risk_aversion_of_second_derivative_relation
    (u' u'' α : ℝ)
    (hu' : u' ≠ 0)
    (hrelation : u'' = -α * u') :
    absolute_risk_aversion u' u'' = α := by
  unfold absolute_risk_aversion
  rw [hrelation]
  field_simp [hu']
