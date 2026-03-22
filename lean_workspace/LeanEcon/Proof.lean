import Mathlib
import Mathlib.GameTheory.NormalForm

/-- Every finite normal-form game has a Nash equilibrium. -/
theorem finite_normal_form_game_has_nash_equilibrium
    {n : ℕ} (players : Fin n → Type*) [∀ i, Fintype (players i)]
    (strategies : ∀ i, players i → Type*) [∀ i, ∀ s, Fintype (strategies i s)]
    (payoffs : ∀ i, (∀ j : Fin n, strategies j (players j)) → ℝ) :
    ∃ s : ∀ i, strategies i (players i), ∀ i, ∀ s' : strategies i (players i),
      payoffs i (Function.update s s' i) ≤ payoffs i s := by
  sorry