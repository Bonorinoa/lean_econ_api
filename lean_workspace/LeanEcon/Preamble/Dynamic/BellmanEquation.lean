import Mathlib

/-- Right-hand side of the Bellman equation for deterministic cake-eating.
    V(k) = u(k - k') + β * V(k') where k' is the policy choice. -/
noncomputable def bellman_rhs (u : ℝ → ℝ) (β : ℝ) (V : ℝ → ℝ) (k k' : ℝ) : ℝ :=
  u (k - k') + β * V k'

/-- The Bellman equation holds at state k given optimal policy k*.
    V(k) = u(k - k*) + β * V(k*). -/
theorem bellman_optimality
    (V u : ℝ → ℝ) (β k k_star : ℝ)
    (h : V k = u (k - k_star) + β * V k_star) :
    V k = bellman_rhs u β V k k_star := h
