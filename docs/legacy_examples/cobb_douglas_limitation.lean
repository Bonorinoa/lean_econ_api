import Mathlib
open Real

/-- Cobb-Douglas production function: f(K,L) = A·K^α·L^(1-α).
    The output elasticity with respect to capital is α. -/
theorem cobb_douglas_elasticity_capital
    (A K L α : ℝ)
    (hA : A > 0) (hK : K > 0) (hL : L > 0) (hα : 0 < α) (hα1 : α < 1) :
    (A * α * K ^ (α - 1) * L ^ (1 - α)) * (K / (A * K ^ α * L ^ (1 - α))) = α := by
  field_simp [hA.ne', hK.ne', hL.ne']
  rw [show α - 1 + 1 = α by ring]
  rw [show (1 - α) + (1 - α) = 2 * (1 - α) by ring]
  rw [← rpow_add hK, ← rpow_mul hL]
  simp only [sub_eq_add_neg, add_comm]
  rw [mul_assoc, mul_assoc]
  rw [← mul_assoc (α * A), mul_comm α]
  ring
