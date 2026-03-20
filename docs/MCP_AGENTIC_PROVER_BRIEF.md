# LeanEcon MCP-First Prover Brief

## Goal

Reengineer LeanEcon's proving stage to support an **agentic Leanstral prover**
that uses `lean-lsp-mcp` for live Lean interaction, while preserving the
current batch prover as a stable fallback and regression baseline.

## Current Status (2026-03-19)

### What is complete

**Phase 0-1: MCP plumbing** — DONE
- `lean-lsp-mcp` launches successfully via `uvx lean-lsp-mcp --transport stdio`
  with `cwd=lean_workspace`
- Raw MCP queries succeed (diagnostics, goals)
- Mistral `RunContext` registers 23 total tools for the agentic loop
- `src/mcp_smoke_test.py` passes end-to-end

**Phase 2: Agentic proving loop** — DONE (initial version)
- `src/agentic_prover.py` implements a real Leanstral+MCP proving loop using
  Mistral's `run_async` Conversations API
- Leanstral drives the loop autonomously via tool calls:
  - MCP tools (lean_diagnostic_messages, lean_goal, etc.) for reading Lean state
  - Custom `apply_tactic` function for writing tactics to the working file
- Final verification via `lake build` (MCP is guidance, not truth)
- `pipeline.py` supports `prover_mode="batch"|"agentic"` (default: `batch`)

**FastAPI mode wiring** — DONE
- `src/api.py` exposes `POST /api/classify`, `POST /api/formalize`, and
  `POST /api/verify`
- `POST /api/verify` forwards `prover_mode="batch"|"agentic"` into
  `pipeline.run_pipeline(..., preformalized_theorem=..., prover_mode=...)`
- The HTTP layer keeps the classify/formalize/review/verify workflow explicit
  for frontend clients without changing the core proving logic

### Validated results (agentic prover)

| Input path | Theorem | Result | Notes |
|-----------|---------|--------|-------|
| Raw Lean | `1 + 1 = 2` | PASS | `norm_num`, ~4 round-trips |
| Raw Lean | CRRA RRA | PASS | `field_simp`, verified locally |
| Raw Lean | Budget constraint | PASS | `exact hspend` |
| Raw Lean | Stone-Geary ΔV | PASS | `ring` |
| Raw Lean | Simplified Cobb-Douglas | PASS | `field_simp [hK.ne']` on `α * K * K⁻¹ = α` |
| Natural language | CRRA RRA | PASS | Formalizes and verifies end to end through the agentic path |
| Natural language | Cobb-Douglas | MIXED / UNSTABLE | Passed in one explicit CLI run, but another diagnostic run still failed |

All passing cases above were verified by `lake build`.

## Architecture

### Two prover implementations

1. **Batch prover** (`src/leanstral_client.py`)
   - Two-stage prompting: strategy → full tactic proof
   - pass@5 with error feedback between attempts
   - Verification via `lake build`
   - Default mode, production-tested

2. **Agentic prover** (`src/agentic_prover.py`)
   - Uses Mistral's `run_async` Conversations API
   - Leanstral calls `lean-lsp-mcp` tools natively for diagnostics/goals
   - Custom `apply_tactic` function writes tactics via `ProofFileController`
   - Final verification via `lake build`
   - Behind `prover_mode="agentic"` flag

### Key design decisions

**Hybrid Approach A**: Leanstral drives the loop via `run_async`, not a Python
controller loop. This works because:
- Leanstral was trained to call `lean-lsp-mcp` tools
- The Mistral SDK's `run_async` handles tool-call dispatch internally
- MCP tools use a persistent session (via RunContext), not per-call subprocess

**Lightweight `apply_tactic`**: The custom function only writes the file — it
does NOT query MCP. Leanstral uses its native MCP tools for diagnostics.
This avoids the 20s/call overhead of spawning a new `lean-lsp-mcp` per query.

**Three-layer proof completion detection**:
1. In-loop: Leanstral checks diagnostics via MCP tools
2. Post-loop: Python checks tactic block doesn't contain `sorry`
3. Final: `lean_verifier.verify()` via `lake build` (authoritative)

## Module responsibilities

| File | Responsibility |
|------|---------------|
| `src/mcp_runtime.py` | MCP server params, sessions, RunContext, query helpers |
| `src/proof_file_controller.py` | Working file management, tactic regions, checkpoints |
| `src/agentic_prover.py` | Agentic loop via `run_async` + `apply_tactic` |
| `src/leanstral_client.py` | Batch prover (two-stage prompting) |
| `src/pipeline.py` | Orchestration with `prover_mode` flag |
| `src/lean_verifier.py` | `lake build` verification |
| `src/formalizer.py` | Claim classification + formalization |

## Local environment

- Project venv: `./econProver_venv/bin/python`
- `mistralai 2.0.4`, `mcp`, `griffe>=1.7.3` installed
- `uv 0.10.7` available (for `uvx lean-lsp-mcp`)
- Lean workspace: `lean_workspace/` (contains `lakefile.toml`)

## Remaining work

### Not yet done
- A/B comparison harness (batch vs agentic on same claims)
- Performance optimization (bulk of time is MCP server startup + lake build)
- Checkpoint scoring policy (currently simple save/restore)
- Loop detection / stop conditions for complex proofs
- Stability work for natural-language Cobb-Douglas before promoting it as fixed

### Known limitations
- Each `run_async` conversation takes ~60s due to MCP server lifecycle
- Natural-language Cobb-Douglas is not yet stable enough to promote: one
  explicit CLI run passed, but another diagnostic run still failed on a
  separate sample
- No mechanism to fall back to batch mode if agentic times out

## Useful commands

```bash
# MCP smoke test
./econProver_venv/bin/python src/mcp_smoke_test.py

# Agentic prover regression checks
./econProver_venv/bin/python tests/test_agentic_examples.py

# FastAPI smoke checks
./econProver_venv/bin/python tests/test_api_smoke.py

# Compile check all source files
./econProver_venv/bin/python -m py_compile src/*.py tests/*.py

# FastAPI app
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

## Source Links

- Mistral Leanstral announcement: https://mistral.ai/news/leanstral
- Mistral MCP docs: https://docs.mistral.ai/agents/tools/mcp
- Leanstral model card: https://huggingface.co/mistralai/Leanstral-2603
- lean-lsp-mcp README: https://github.com/oOo0oOo/lean-lsp-mcp
