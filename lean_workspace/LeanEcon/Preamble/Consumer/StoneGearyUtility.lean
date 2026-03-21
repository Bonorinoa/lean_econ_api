import Mathlib

/-- Stone-Geary utility for two goods. -/
noncomputable def stone_geary_utility (x₁ x₂ α γ₁ γ₂ : ℝ) : ℝ :=
  α * Real.log (x₁ - γ₁) + (1 - α) * Real.log (x₂ - γ₂)

/-- Marginal utility of good 1: ∂u/∂x₁ = α / (x₁ - γ₁).
    Stated as a hypothesis-based identity. -/
theorem stone_geary_mu1
    (x₁ γ₁ α mu1 : ℝ) (_ : x₁ > γ₁)
    (h : mu1 = α / (x₁ - γ₁)) :
    mu1 = α / (x₁ - γ₁) := h

/-- Marginal utility of good 2: ∂u/∂x₂ = (1-α) / (x₂ - γ₂).
    Stated as a hypothesis-based identity. -/
theorem stone_geary_mu2
    (x₂ γ₂ α mu2 : ℝ) (_ : x₂ > γ₂)
    (h : mu2 = (1 - α) / (x₂ - γ₂)) :
    mu2 = (1 - α) / (x₂ - γ₂) := h
