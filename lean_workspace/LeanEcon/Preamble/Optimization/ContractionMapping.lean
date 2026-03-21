import Mathlib

/-- A map T on bounded real-valued functions is a contraction with modulus β
    if d(T(f), T(g)) ≤ β * d(f, g) for all f, g, where d is the sup-norm. -/
def is_contraction_sup (T : (ℝ → ℝ) → (ℝ → ℝ)) (β : ℝ) : Prop :=
  0 ≤ β ∧ β < 1 ∧
  ∀ f g : ℝ → ℝ, ∀ x : ℝ, |T f x - T g x| ≤ β * |f x - g x|
