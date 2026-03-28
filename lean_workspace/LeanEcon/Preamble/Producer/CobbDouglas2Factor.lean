import Mathlib

/-- Two-factor Cobb-Douglas production function. -/
noncomputable def cobb_douglas (A K L α : ℝ) : ℝ :=
  A * Real.rpow K α * Real.rpow L (1 - α)

/-- The marginal product of capital in a two-factor Cobb-Douglas production function. -/
theorem cobb_douglas_hasDerivAt_capital
    (A L α K : ℝ)
    (hK : K ≠ 0 ∨ 1 ≤ α) :
    HasDerivAt
      (fun k => cobb_douglas A k L α)
      (A * (α * Real.rpow K (α - 1)) * Real.rpow L (1 - α))
      K := by
  dsimp [cobb_douglas]
  have hk : HasDerivAt (fun k => Real.rpow k α) (α * Real.rpow K (α - 1)) K :=
    Real.hasDerivAt_rpow_const hK
  simpa [mul_assoc, mul_left_comm, mul_comm] using
    ((hasDerivAt_const K A).mul (hk.mul_const (Real.rpow L (1 - α))))

/-- The derivative of Cobb-Douglas output with respect to capital. -/
theorem cobb_douglas_deriv_capital
    (A L α K : ℝ)
    (hK : K ≠ 0 ∨ 1 ≤ α) :
    deriv (fun k => cobb_douglas A k L α) K =
      A * (α * Real.rpow K (α - 1)) * Real.rpow L (1 - α) :=
  (cobb_douglas_hasDerivAt_capital A L α K hK).deriv

/-- Output elasticity w.r.t. capital: (∂f/∂K)·(K/f) = α.
    After substituting and canceling all A, L, and K^α terms,
    the expression reduces to α · K · K⁻¹ = α. -/
theorem cobb_douglas_elasticity_capital
    (α K : ℝ) (_ : 0 < α) (_ : α < 1) (hK : K > 0) :
    α * K * K⁻¹ = α := by
  field_simp
