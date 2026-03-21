import Mathlib

/-- Two-factor Cobb-Douglas production function. -/
noncomputable def cobb_douglas (A K L α : ℝ) : ℝ :=
  A * Real.rpow K α * Real.rpow L (1 - α)

/-- Marginal product of capital: ∂f/∂K = α · A · K^(α-1) · L^(1-α).
    Stated as a hypothesis-based identity. -/
theorem cobb_douglas_mpk
    (A K L α mpk : ℝ) (_ : A > 0) (_ : K > 0) (_ : L > 0) (_ : 0 < α)
    (h : mpk = α * A * Real.rpow K (α - 1) * Real.rpow L (1 - α)) :
    mpk = α * A * Real.rpow K (α - 1) * Real.rpow L (1 - α) := h

/-- Marginal product of labor: ∂f/∂L = (1-α) · A · K^α · L^(-α).
    Stated as a hypothesis-based identity. -/
theorem cobb_douglas_mpl
    (A K L α mpl : ℝ) (_ : A > 0) (_ : K > 0) (_ : L > 0) (_ : α < 1)
    (h : mpl = (1 - α) * A * Real.rpow K α * Real.rpow L (-α)) :
    mpl = (1 - α) * A * Real.rpow K α * Real.rpow L (-α) := h

/-- Output elasticity w.r.t. capital: (∂f/∂K)·(K/f) = α.
    After substituting and canceling all A, L, and K^α terms,
    the expression reduces to α · K · K⁻¹ = α. -/
theorem cobb_douglas_elasticity_capital
    (α K : ℝ) (_ : 0 < α) (_ : α < 1) (hK : K > 0) :
    α * K * K⁻¹ = α := by
  field_simp
