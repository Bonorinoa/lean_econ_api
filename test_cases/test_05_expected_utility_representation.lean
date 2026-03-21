import Mathlib

namespace ExpectedUtilityRepresentation

abbrev Lottery (α : Type*) := PMF α

/-- A finite-lottery preference with VNM-style axioms recorded as fields. -/
structure FiniteVNMPreference (α : Type*) [Fintype α] where
  prefers : Lottery α → Lottery α → Prop
  complete : ∀ p q, prefers p q ∨ prefers q p
  transitive : ∀ {p q r}, prefers p q → prefers q r → prefers p r
  independence : Prop
  continuity : Prop

/-- Expected utility of a finite lottery under cardinal index `u`. -/
noncomputable def expectedUtility {α : Type*} [Fintype α] [DecidableEq α]
    (u : α → ℝ) (p : Lottery α) : ℝ :=
  Finset.univ.sum fun a => ENNReal.toReal (p a) * u a

lemma expected_utility_pure
    {α : Type*} [Fintype α] [DecidableEq α]
    (u : α → ℝ) (a : α) :
    expectedUtility u (PMF.pure a) = u a := by
  sorry

theorem exists_expected_utility_representation
    {α : Type*} [Fintype α] [DecidableEq α]
    (pref : FiniteVNMPreference α) :
    ∃ u : α → ℝ, ∀ p q : Lottery α,
      pref.prefers p q ↔ expectedUtility u q ≤ expectedUtility u p := by
  sorry

end ExpectedUtilityRepresentation
