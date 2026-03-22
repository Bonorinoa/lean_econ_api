# LeanEcon Workspace

This directory contains the Lean 4 workspace used by the API and Docker build.

- `LeanEcon.lean` is the default library target built during image creation.
- `LeanEcon/Preamble/` contains reusable economics definitions.
- Runtime verification uses isolated `AgenticProof_*.lean` files compiled with
  `lake env lean`.
- `LeanEcon/Proof.lean` is kept only as a fixed fallback file for
  sorry-validation when MCP-backed `lean_run_code` is unavailable.
