import Mathlib
import LeanEcon.Preamble.Consumer.CRRAUtility

/-- Under CRRA utility u(c) = c^(1-gamma)/(1-gamma), relative risk aversion simplifies to gamma. -/
theorem crra_relative_risk_aversion_leanecon_1d2644
    (γ : ℝ) (c : ℝ) (hγ : γ ≠ 1) (hc : c > 0) :
    relative_risk_aversion c (fun c => c ^ (1 - γ) / (1 - γ)) (fun c => c ^ (-γ)) = γ := by
  sorry