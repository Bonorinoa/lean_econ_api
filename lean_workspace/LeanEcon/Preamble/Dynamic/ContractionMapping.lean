import Mathlib

/-- A contracting self-map on a complete metric space has a unique fixed point. -/
theorem contraction_has_unique_fixed_point
    {α : Type*} [MetricSpace α] [CompleteSpace α] [Nonempty α]
    (β : NNReal) (f : α → α)
    (hf : ContractingWith β f) :
    ∃! x, f x = x := by
  refine ⟨ContractingWith.fixedPoint f hf, hf.fixedPoint_isFixedPt, ?_⟩
  intro x hx
  exact hf.fixedPoint_unique hx
