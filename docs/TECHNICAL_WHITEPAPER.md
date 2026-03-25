# LeanEcon Technical White Paper

## Abstract

LeanEcon is a Lean-backed verification system for mathematical claims in
economics and adjacent mathematics. The design goal is not to hide proof
engineering behind a black-box model; it is to combine stochastic generation
with deterministic Lean kernel acceptance and an explicit human review step.

The current public runtime paths are:

- optional claim classification for frontend UX
- claim shaping through `POST /api/v1/formalize`
- direct local Lean compilation through `POST /api/v1/lean_compile`
- asynchronous agentic proving plus final verification through `POST /api/v1/verify`

LeanEcon is strongest when the statement is already well formed. The weakest
lane is still raw-claim end-to-end evaluation, which means claim shaping and
formalization remain the main product bottleneck.

## Design Goal

The intended user experience is:

1. start from plain English, LaTeX, theorem stubs, or raw Lean
2. formalize the statement into Lean when needed
3. let a human or agent inspect the theorem statement
4. prove it with an agentic Lean-aware prover when required
5. trust only the final Lean compiler result

This keeps the system aligned with proof engineering rather than probabilistic
answer generation. The optional `/api/v1/lean_compile` path is a thin
synchronous compile/debug primitive for complete Lean source, not the default
workflow.

## Trust Model

LeanEcon uses a three-layer trust model:

1. Stochastic generation
   - Leanstral proposes formalizations and tactic sequences.
2. Human review
   - clients can inspect or edit theorem code before proving.
3. Deterministic acceptance
   - final truth comes from Lean 4 compiled with the repo's local Lean and
     Mathlib environment.

The core invariant is simple: no model output is treated as verified until the
local Lean toolchain accepts it without `sorry`.

## System Architecture

Current architecture, grounded in the repo:

- [`src/api.py`](../src/api.py): FastAPI service and public contract
- [`src/formalizer.py`](../src/formalizer.py): claim-to-theorem translation and
  bounded repair
- [`src/formalization_search.py`](../src/formalization_search.py): curated
  retrieval and preamble matching
- [`src/pipeline.py`](../src/pipeline.py): parse -> formalize -> prove ->
  verify orchestration
- [`src/agentic_prover.py`](../src/agentic_prover.py): Leanstral + MCP proving
  loop with local tool budgets
- [`src/lean_verifier.py`](../src/lean_verifier.py): isolated-file compilation
  via `lake env lean`
- [`src/result_cache.py`](../src/result_cache.py): verified-result cache
- [`src/job_store.py`](../src/job_store.py): async verify job tracking and SSE

### Formalization

The formalizer translates natural language or LaTeX into a Lean theorem with
`:= by sorry`, then runs sorry-tolerant validation before the prover sees it.
It uses:

- bounded retrieval context
- optional or auto-selected LeanEcon preambles
- bucketed repairs for import, identifier, typeclass, syntax, and semantic
  failures
- MCP-backed search when available, with local Lean compilation as fallback

Raw Lean input that already looks like a theorem stub bypasses formalization and
passes through unchanged with `attempts = 0`.

### Direct Compile Path

`POST /api/v1/lean_compile` compiles user-provided Lean code directly with the
repo's Lean environment. It bypasses the formalizer and prover entirely. This
is useful for clients that already have Lean code and only need kernel-truth
diagnostics or a quick debug loop.

### Agentic Proving

The proving path is MCP-first. Leanstral interacts with a small allowed tool
surface, including:

- `lean_goal`
- `lean_diagnostic_messages`
- selected search and suggestion tools
- local `apply_tactic`

The controller keeps the working file, applies tool budgets, captures traces,
and relies on the local compiler rather than MCP for final truth.

### Final Verification

Final acceptance uses isolated per-run files compiled directly with
`lake env lean`. This replaced the older shared `Proof.lean` bottleneck and is
the key reason concurrent verification is now safe.

## Public API Surface

The current public v1 API includes:

- `POST /api/v1/classify`
- `POST /api/v1/formalize`
- `POST /api/v1/lean_compile`
- `POST /api/v1/verify`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/jobs/{job_id}/stream`
- `POST /api/v1/explain`
- `GET /api/v1/metrics`
- `GET /api/v1/benchmarks/latest`
- `GET /api/v1/cache/stats`
- `DELETE /api/v1/cache`

The important product distinction is that `lean_compile` is a thin synchronous
compile/debug primitive, while `verify` is asynchronous and invokes the
agentic prover.

## Benchmark Evidence

The current benchmark story is mixed but honest.

From the latest completed tier-1 full report
[`benchmarks/reports/tier1_core_selected_full_full_20260325T151134Z.md`](../benchmarks/reports/tier1_core_selected_full_full_20260325T151134Z.md):

- `raw_claim -> full API`: `pass@1 = 0.333`
- `theorem_stub -> verify`: `pass@1 = 1.000`
- `raw_lean -> verify`: `pass@1 = 1.000`

From the latest completed tier-1 formalizer-only report
[`benchmarks/reports/tier1_core_formalizer_only_20260325T181104Z.md`](../benchmarks/reports/tier1_core_formalizer_only_20260325T181104Z.md):

- `raw_claim -> formalizer-only gate`: `pass@1 = 0.833`
- semantic `>=4` rate: `1.000`

This implies:

- the Lean runtime and proving path are already strong when the statement is
  well formed
- the main engineering bottleneck is still full end-to-end raw-claim reliability
  after claim shaping, not final Lean acceptance of already well-formed inputs
- user-facing UX should continue to privilege raw Lean and theorem-stub paths
  as the fastest and most reliable modes

A live production smoke check on 2026-03-25 also returned `200` across
`/health`, `/openapi.json`, `/api/v1/metrics`, `/api/v1/cache/stats`, classify,
and formalize, and completed the sample verify job successfully on the deployed
Railway service. That runtime check reinforces the same point: deployment and
verify lanes are healthy once the statement is already in good Lean form.

## Strengths

- Lean is the final authority
- Verification is concurrency-safe via isolated temp files
- The codebase has strong test coverage for non-live paths
- There is a real evaluation harness instead of only ad hoc examples
- Formalization, proving, verification, and explanation are separated cleanly
- The direct compile path exposes the repo's Lean environment as standalone
  value

## Current Limitations

- Natural-language formalization is still the least stable stage
- Proof search remains stochastic
- `Real.rpow`-heavy and structure-heavy economics claims remain brittle
- Leanstral is an external dependency, so pricing, quota, and long-term
  availability should be treated as provisional
- The repo now records conservative provider-usage telemetry and estimated
  cost bounds when usage payloads are present, but those estimates are for
  observability only, do not imply a stable free tier, and public pricing
  claims should remain conservative
- Direct Lean compilation stays local-only and is excluded from LLM spend

## Operational Notes

- The Docker path is the intended deployment and validation path
- Runtime state can be persisted via `LEANECON_STATE_DIR`
- The API is not a fit for serverless platforms that lack the local Lean
  toolchain
- Direct compile and final verification both derive value from shipping the Lean
  environment itself, not just the agentic layers
- The README is the landing page, and `docs/API.md` is the canonical operational
  guide

## Conclusion

LeanEcon is already more than a demo. It is a compact Lean-backed verification
system with a credible public API, a tested runtime, and a measurable benchmark
story. The right next step is not to pretend the frontier problem is solved. It
is to package the current strengths properly, keep the public docs honest, and
continue improving the formalizer, which remains the dominant bottleneck for
natural-language use.
