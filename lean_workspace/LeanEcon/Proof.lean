import Mathlib
import LeanEcon.Preamble.Consumer.CRRAUtility

open Real

/-- The relative risk aversion of the CRRA utility function u(c) = c^(1-γ)/(1-γ) is γ. -/
theorem crra_rra_leanecon_1d2644 (c γ : ℝ) (hc : c > 0) (hγ : γ > 0) (hγ1 : γ ≠ 1) :
  -c * (deriv (fun x => crra_utility x γ) c) / (crra_utility c γ) = γ := by
  sorry
