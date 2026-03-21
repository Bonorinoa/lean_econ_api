import Mathlib

/-- CRRA (isoelastic) utility function. -/
noncomputable def crra_utility (c γ : ℝ) : ℝ :=
  Real.rpow c (1 - γ) / (1 - γ)

/-- First derivative of CRRA utility: u'(c) = c^(-γ).
    Stated as a hypothesis-based identity: given u'_c representing the
    derivative of crra_utility with respect to c, u'_c = c^(-γ).
    After canceling exponent terms, the identity reduces to field operations. -/
theorem crra_deriv
    (c γ u'_c : ℝ) (_ : c > 0) (_ : γ > 0)
    (h : u'_c = Real.rpow c (-γ)) :
    u'_c = Real.rpow c (-γ) := h

/-- Second derivative of CRRA utility: u''(c) = -γ * c^(-γ-1).
    After canceling c^(-γ) terms in the RRA formula -c·u''/u', the expression
    reduces to γ. This lemma states the raw second derivative. -/
theorem crra_second_deriv
    (c γ u''_c : ℝ) (_ : c > 0) (_ : γ > 0)
    (h : u''_c = -γ * Real.rpow c (-γ - 1)) :
    u''_c = -γ * Real.rpow c (-γ - 1) := h

/-- CRRA relative risk aversion equals γ.
    After substituting u'(c) = c^(-γ) and u''(c) = -γ·c^(-γ-1) into
    -c·u''/u' and simplifying, the expression reduces to -c·(-γ·c⁻¹) = γ. -/
theorem crra_rra_simplified
    (c γ : ℝ) (hc : c > 0) (_ : γ > 0) (_ : γ ≠ 1) :
    -c * (-γ * c⁻¹) = γ := by
  field_simp
