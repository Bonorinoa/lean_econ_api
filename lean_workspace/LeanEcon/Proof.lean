import Mathlib
open Real

/-- The Envelope Theorem: The derivative of the value function with respect to the state variable
    equals the partial derivative of the objective function evaluated at the optimal policy. -/
theorem envelope_theorem
    {X : Type*} [NormedAddCommGroup X] [NormedSpace ℝ X]
    {U : ℝ × X → ℝ}
    {V : ℝ → ℝ}
    {x : ℝ → X}
    (hU : Differentiable ℝ (fun p : ℝ × X => U p))
    (hV : Differentiable ℝ V)
    (hx : Differentiable ℝ x)
    (h_optimal : ∀ t, V t = U (t, x t))
    (t₀ : ℝ) :
    deriv V t₀ = (deriv (fun p : ℝ × X => U p) (t₀, x t₀)).1 := by
  sorry