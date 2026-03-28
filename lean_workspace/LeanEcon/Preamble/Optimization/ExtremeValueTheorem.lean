import Mathlib

/- Extreme value theorem (Weierstrass): a continuous real-valued function
   on a nonempty compact set attains its maximum and minimum.
   Re-exports Mathlib's IsCompact.exists_isMaxOn and IsCompact.exists_isMinOn. -/

/-- A continuous function on a nonempty compact set attains a maximum. -/
theorem continuous_attains_max_on_compact
    {α : Type*} [TopologicalSpace α]
    {s : Set α} {f : α → ℝ}
    (hs : IsCompact s) (hne : s.Nonempty)
    (hf : ContinuousOn f s) :
    ∃ x ∈ s, IsMaxOn f s x :=
  hs.exists_isMaxOn hne hf

/-- A continuous function on a nonempty compact set attains a minimum. -/
theorem continuous_attains_min_on_compact
    {α : Type*} [TopologicalSpace α]
    {s : Set α} {f : α → ℝ}
    (hs : IsCompact s) (hne : s.Nonempty)
    (hf : ContinuousOn f s) :
    ∃ x ∈ s, IsMinOn f s x :=
  hs.exists_isMinOn hne hf

/-- Strict concavity is a common economics-side hypothesis for existence of an optimum. -/
theorem strictly_concave_attains_max_on_compact
    {α : Type*} [TopologicalSpace α] [AddCommMonoid α] [Module ℝ α]
    {s : Set α} {f : α → ℝ}
    (hs : IsCompact s) (hne : s.Nonempty)
    (hf : ContinuousOn f s)
    (_ : StrictConcaveOn ℝ s f) :
    ∃ x ∈ s, IsMaxOn f s x :=
  continuous_attains_max_on_compact hs hne hf

/-- Strict convexity is a common economics-side hypothesis for existence of a minimizer. -/
theorem strictly_convex_attains_min_on_compact
    {α : Type*} [TopologicalSpace α] [AddCommMonoid α] [Module ℝ α]
    {s : Set α} {f : α → ℝ}
    (hs : IsCompact s) (hne : s.Nonempty)
    (hf : ContinuousOn f s)
    (_ : StrictConvexOn ℝ s f) :
    ∃ x ∈ s, IsMinOn f s x :=
  continuous_attains_min_on_compact hs hne hf
