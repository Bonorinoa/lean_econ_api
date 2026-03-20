import Mathlib

/--
A placeholder theorem that keeps the Lean workspace buildable between runs.

`lean_verifier.write_lean_file()` overwrites this module during verification.
-/
theorem lean_econ_placeholder : 1 + 1 = 2 := by
  norm_num
