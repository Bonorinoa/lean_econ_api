import Mathlib.Analysis.Calculus.Deriv.Basic
import Mathlib.Analysis.Calculus.FDeriv.Basic
import LeanEcon.Preamble.Dynamic.BellmanEquation

open Real

/-- The Envelope Theorem: the derivative of the value function with respect to the state variable
    equals the partial derivative of the objective function evaluated at the optimal policy. -/
theorem envelope_theorem_leanecon_979126
    (u : ℝ → ℝ) (β : ℝ) (V : ℝ → ℝ) (k : ℝ)
    (hβ : 0 < β) (hβ1 : β < 1)
    (hV : DifferentiableAt ℝ V k)
    (hbellman : ∀ k', V k = u (k - k') + β * V k')
    (hoptimal : ∀ k', V k ≤ u (k - k') + β * V k')
    (hderiv : ∀ k', DifferentiableAt ℝ (fun k' => u (k - k') + β * V k') k') :
    deriv V k = deriv (fun k' => u (k - k') + β * V k') k := by
  sorry
