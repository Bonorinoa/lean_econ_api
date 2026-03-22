import Mathlib
import Mathlib.Analysis.Calculus.Deriv.Basic
import Mathlib.Analysis.Convex.Basic
import Mathlib.Topology.Basic

open Real

/-- The Envelope Theorem: The derivative of the value function with respect to the state variable
    equals the partial derivative of the objective function evaluated at the optimal policy. -/
theorem envelope_theorem
    (f : ℝ → ℝ → ℝ) (g : ℝ → ℝ) (x : ℝ) (hx : DifferentiableAt ℝ g x)
    (hf : ∀ y, DifferentiableAt ℝ (fun z => f z y) x)
    (hf' : ∀ y, DifferentiableAt ℝ (fun z => f z y) (g x))
    (h_opt : IsLocalMax (fun y => f x y) (g x))
    : deriv (fun z => f z (g z)) x = deriv (fun y => f x y) (g x) := by
  sorry