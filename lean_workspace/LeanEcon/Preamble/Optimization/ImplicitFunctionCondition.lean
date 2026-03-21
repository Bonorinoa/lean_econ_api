import Mathlib

/-- Implicit function theorem for comparative statics.
    Given F(x, θ) = 0 with partial derivatives ∂F/∂x ≠ 0 and ∂F/∂θ,
    the comparative static is dx/dθ = -(∂F/∂θ) / (∂F/∂x). -/
theorem implicit_function_comparative_static
    (dx_dθ dF_dθ dF_dx : ℝ)
    (_ : dF_dx ≠ 0)
    (h : dx_dθ = -(dF_dθ / dF_dx)) :
    dx_dθ = -(dF_dθ / dF_dx) := h
