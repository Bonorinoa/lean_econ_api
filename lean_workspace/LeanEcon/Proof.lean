import Mathlib

/--
Legacy placeholder module reserved for fixed-path sorry-validation fallback.

This file is intentionally not imported by `LeanEcon.lean`; runtime
verification uses isolated `AgenticProof_*.lean` files compiled directly with
`lake env lean`.
-/
theorem legacy_proof_module_placeholder : True := by
  trivial
