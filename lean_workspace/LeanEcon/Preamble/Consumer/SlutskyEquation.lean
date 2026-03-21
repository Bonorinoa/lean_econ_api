import Mathlib

/-- Slutsky equation as an algebraic identity.
    Given Marshallian demand derivative ∂xᵢ/∂pⱼ, Hicksian demand derivative ∂hᵢ/∂pⱼ,
    demand for good j (xⱼ), and income derivative ∂xᵢ/∂m, the Slutsky decomposition
    states: ∂xᵢ/∂pⱼ = ∂hᵢ/∂pⱼ - xⱼ · ∂xᵢ/∂m. -/
theorem slutsky_identity
    (dxi_dpj dhi_dpj xj dxi_dm : ℝ)
    (h : dxi_dpj = dhi_dpj - xj * dxi_dm) :
    dxi_dpj = dhi_dpj - xj * dxi_dm := h
