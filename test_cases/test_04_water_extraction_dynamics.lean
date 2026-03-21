import Mathlib
import LeanEcon.Preamble.Dynamic.DiscountFactor

open Real

namespace WaterExtractionDynamics

/-- One-step groundwater law of motion. -/
def nextStock (s recharge extraction : ℝ) : ℝ :=
  s + recharge - extraction

/-- Terminal groundwater stock after two extraction periods. -/
def terminalStock (s₀ recharge₀ recharge₁ extraction₀ extraction₁ : ℝ) : ℝ :=
  nextStock (nextStock s₀ recharge₀ extraction₀) recharge₁ extraction₁

/-- A linearized two-period resource objective with a shadow price on terminal stock. -/
def waterObjective
    (v₀ v₁ shadowPrice s₀ recharge₀ recharge₁ extraction₁ : ℝ) : ℝ → ℝ :=
  fun extraction₀ =>
    v₀ * extraction₀ + v₁ * extraction₁
      + shadowPrice * terminalStock s₀ recharge₀ recharge₁ extraction₀ extraction₁

lemma terminal_stock_identity
    (s₀ recharge₀ recharge₁ extraction₀ extraction₁ : ℝ) :
    terminalStock s₀ recharge₀ recharge₁ extraction₀ extraction₁
      = s₀ + recharge₀ + recharge₁ - extraction₀ - extraction₁ := by
  sorry

lemma water_objective_deriv
    (v₀ v₁ shadowPrice s₀ recharge₀ recharge₁ extraction₁ extraction₀ : ℝ) :
    deriv (waterObjective v₀ v₁ shadowPrice s₀ recharge₀ recharge₁ extraction₁) extraction₀
      = v₀ - shadowPrice := by
  sorry

theorem groundwater_first_order_stationarity
    (v₀ v₁ shadowPrice s₀ recharge₀ recharge₁ extraction₁ extraction₀ : ℝ)
    (hFOC :
      deriv (waterObjective v₀ v₁ shadowPrice s₀ recharge₀ recharge₁ extraction₁) extraction₀ = 0) :
    v₀ = shadowPrice := by
  sorry

end WaterExtractionDynamics
