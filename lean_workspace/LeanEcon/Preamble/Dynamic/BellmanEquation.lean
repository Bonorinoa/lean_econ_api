import Mathlib

open scoped BoundedContinuousFunction
open BoundedContinuousFunction

/-- Right-hand side of the Bellman equation for deterministic cake-eating.
    V(k) = u(k - k') + β * V(k') where k' is the policy choice. -/
noncomputable def bellman_rhs (u : ℝ → ℝ) (β : ℝ) (V : ℝ → ℝ) (k k' : ℝ) : ℝ :=
  u (k - k') + β * V k'

/-- Discounted continuation value on bounded continuous functions. -/
noncomputable def discounted_continuation
    {α : Type*} [TopologicalSpace α]
    (β : NNReal) (f : ContinuousMap α α) (V : α →ᵇ ℝ) : α →ᵇ ℝ :=
  (β : ℝ) • V.compContinuous f

/-- Bellman operator with deterministic transition and bounded continuous payoff. -/
noncomputable def bellman_operator
    {α : Type*} [TopologicalSpace α]
    (β : NNReal) (u : α →ᵇ ℝ) (f : ContinuousMap α α) (V : α →ᵇ ℝ) : α →ᵇ ℝ :=
  u + discounted_continuation β f V

/-- Discounted continuation is `β`-Lipschitz in the sup norm. -/
theorem discounted_continuation_dist_le
    {α : Type*} [TopologicalSpace α] [Nonempty α]
    (β : NNReal) (f : ContinuousMap α α) (V W : α →ᵇ ℝ) :
    dist (discounted_continuation β f V) (discounted_continuation β f W) ≤ β * dist V W := by
  rw [BoundedContinuousFunction.dist_le_iff_of_nonempty]
  intro x
  change
    dist (((β : ℝ) • V.compContinuous f) x) (((β : ℝ) • W.compContinuous f) x) ≤
      β * dist V W
  simpa [discounted_continuation, mul_comm, mul_left_comm, mul_assoc] using
    (dist_smul_le (β : ℝ) (V (f x)) (W (f x))).trans
      (mul_le_mul_of_nonneg_left (BoundedContinuousFunction.dist_coe_le_dist (f x))
        (by positivity))

/-- The Bellman operator inherits the same `β`-Lipschitz bound. -/
theorem bellman_operator_dist_le
    {α : Type*} [TopologicalSpace α] [Nonempty α]
    (β : NNReal) (u : α →ᵇ ℝ) (f : ContinuousMap α α) (V W : α →ᵇ ℝ) :
    dist (bellman_operator β u f V) (bellman_operator β u f W) ≤ β * dist V W := by
  simpa [bellman_operator] using discounted_continuation_dist_le β f V W

/-- With `β < 1`, the Bellman operator is a contraction in the sup norm. -/
theorem bellman_operator_contractingWith
    {α : Type*} [TopologicalSpace α] [Nonempty α]
    (β : NNReal) (hβ : β < 1) (u : α →ᵇ ℝ) (f : ContinuousMap α α) :
    ContractingWith β (fun V : α →ᵇ ℝ => bellman_operator β u f V) := by
  refine ⟨hβ, LipschitzWith.of_dist_le_mul ?_⟩
  intro V W
  exact bellman_operator_dist_le β u f V W
