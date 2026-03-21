# LeanEcon MCP-First Prover Brief

## Goal

LeanEcon now ships an agentic-only prover built around Leanstral and
`lean-lsp-mcp`. The prover interacts with Lean through MCP tools during the
proof search and uses `lake build` as the final authority.

## Current Status

### What is complete

- `lean-lsp-mcp` launches successfully from `lean_workspace/`
- raw MCP diagnostics and goal queries succeed through `src/mcp_smoke_test.py`
- `src/agentic_prover.py` runs Leanstral through Mistral's `run_async`
- `src/pipeline.py` is agentic-only and returns normalized prover trace data
- `logs/runs.jsonl` now stores richer `tool_trace` / `tactic_calls` records plus the original claim text
- `src/api.py` exposes classify, formalize, verify, jobs, and explain endpoints
- the preamble library is backed by Lean modules under `lean_workspace/LeanEcon/Preamble/`

### Validated results

| Input path | Theorem | Result | Notes |
|-----------|---------|--------|-------|
| Raw Lean | `1 + 1 = 2` | PASS | `norm_num`, low round-trip count |
| Raw Lean | CRRA RRA | PASS | verified locally through the agentic path |
| Raw Lean | Simplified Cobb-Douglas | PASS | stochastic but observed locally |
| Natural language | CRRA RRA | PASS | formalizes and verifies end to end |
| Natural language | Cobb-Douglas | MIXED | still unstable on harder samples |

All passing cases above were verified by `lake build`.

## Architecture

### Core modules

| File | Responsibility |
|------|---------------|
| `src/mcp_runtime.py` | MCP server params, sessions, RunContext, query helpers |
| `src/proof_file_controller.py` | Working-file management and tactic regions |
| `src/agentic_prover.py` | Agentic proving loop via `run_async` |
| `src/pipeline.py` | Orchestration for formalize → prove → verify |
| `src/formalizer.py` | Claim classification + formalization |
| `src/preamble_library.py` | File-backed preamble metadata and lookup |
| `src/leanstral_utils.py` | Shared Leanstral API helpers |
| `src/lean_verifier.py` | Final Lean compiler verification |
| `src/eval_metrics.py` | Shared deep-trace metric aggregation |
| `src/semantic_alignment.py` | Offline semantic grading helpers |

### Key design decisions

- Leanstral drives the proving loop through `run_async`; Python does not micromanage tactic selection.
- `apply_tactic` is intentionally lightweight and only edits the working file.
- MCP tools are used for in-loop diagnostics and goal inspection.
- The prover now persists ordered deep traces with parsed diagnostic payloads so retries can be analyzed offline.
- `lake build` remains the final source of truth for proof acceptance.
- Economic preambles live in Lean modules so their source is validated by the Lean kernel.

## Local Environment

- Project venv: `./leanEconAPI_venv/bin/python`
- Lean workspace: `lean_workspace/`
- Lean version: 4.28.0
- Mathlib version: 4.28.0
- MCP smoke test: `./leanEconAPI_venv/bin/python src/mcp_smoke_test.py`

## Known Limitations

- Each full agentic run still has noticeable latency from MCP setup and Lean verification.
- Proof search remains stochastic.
- Hard `Real.rpow`-heavy or structure-heavy economics claims are not yet stable enough to treat as solved.
- The offline semantic grader is useful for evaluation, but it is not part of the normal `/verify` API path.

## Useful Commands

```bash
# MCP smoke test
./leanEconAPI_venv/bin/python src/mcp_smoke_test.py

# Agentic prover regression checks
./leanEconAPI_venv/bin/python tests/test_agentic_examples.py

# FastAPI smoke checks
./leanEconAPI_venv/bin/python tests/test_api_smoke.py

# Phase 1 stress suite
./leanEconAPI_venv/bin/python scripts/run_phase1_stress_tests.py

# Deep trace analysis
./leanEconAPI_venv/bin/python scripts/analyze_traces.py --runs-file logs/runs.jsonl --format both

# Semantic alignment grading
./leanEconAPI_venv/bin/python scripts/semantic_grader.py --claim "1 + 1 = 2" --theorem-file examples/even_form_pass.lean

# Advanced pass@k evaluation harness
./leanEconAPI_venv/bin/python scripts/run_uncharted_evals.py <claims.jsonl> --pass-k 5

# FastAPI app
uvicorn src.api:app --host 0.0.0.0 --port 8000
```
