import Mathlib

/-- Arrow-Pratt coefficient of relative risk aversion. -/
noncomputable def relative_risk_aversion (c u' u'' : ℝ) : ℝ :=
  -(c * u'') / u'

/-- If the second derivative equals `-(γ / c) * u'`, then relative risk aversion is `γ`. -/
theorem relative_risk_aversion_of_second_derivative_relation
    (c u' u'' γ : ℝ)
    (hc : c ≠ 0)
    (hu' : u' ≠ 0)
    (hrelation : u'' = -(γ / c) * u') :
    relative_risk_aversion c u' u'' = γ := by
  unfold relative_risk_aversion
  rw [hrelation]
  field_simp [hc, hu']
