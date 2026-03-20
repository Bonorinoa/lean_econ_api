import Mathlib
open Real

/-- Under Stone-Geary + log utility, the indirect utility gap ΔV = V_B - V_A
    is exactly constant in income σ. The ln(σ - m̄) terms cancel. -/
theorem log_utility_constant_delta_v
    (α_A α_B p m_bar σ : ℝ)
    (hαA : 0 < α_A) (hαA1 : α_A < 1)
    (hαB : 0 < α_B) (hαB1 : α_B < 1)
    (hp : 0 < p) (hσ : m_bar < σ) :
    (α_B * Real.log (α_B / p) + (1 - α_B) * Real.log (1 - α_B) + Real.log (σ - m_bar))
    - (α_A * Real.log (α_A / p) + (1 - α_A) * Real.log (1 - α_A) + Real.log (σ - m_bar))
    = (α_B * Real.log (α_B / p) + (1 - α_B) * Real.log (1 - α_B))
    - (α_A * Real.log (α_A / p) + (1 - α_A) * Real.log (1 - α_A)) := by
    ring
