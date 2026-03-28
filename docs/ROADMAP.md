# LeanEcon Roadmap

## Investigation-driven priorities (March 25, 2026)

This section reflects the March 25, 2026 audit of the harness, bounded
formalizer, agentic prover, and Lovable frontend handoff behavior.

### P0: unblock the slowest and noisiest runtime paths

- [ ] Restore a reliable fast formalizer validation path so formalization does not keep falling back to `lake env lean`
- [ ] Fix explicit preamble handoff in Lovable pipeline flows, including `Use 1 in Pipeline`, theorem-card `Pipeline`, and `Skip classify`
- [ ] Expose formalizer/prover telemetry needed to debug timeouts, partial proofs, retrieval skips, and validation method choices

### P1: connect retrieval, proving, and observability

- [ ] Enable and harden formalization MCP retrieval/search as an intentional runtime feature rather than an optional dormant path
- [ ] Pass structured retrieval context from the formalizer into the prover instead of handing off only a theorem string
- [ ] Add a prover wall-clock cap and append-round cap separate from the current per-request Conversations timeout
- [ ] Add benchmark lanes and dashboards for partial proofs, timeout frequency, append-round counts, and tool-call efficiency

### P2: reduce retrieval noise before broadening scope

- [ ] Improve preamble ranking and merge policy to reduce noisy multi-preamble injection
- [ ] Expand theorem-library coverage only after the runtime path is measurably more stable

### Framing updates from the investigation

- Frontend development is now primarily a reliability-integration problem: preserve preamble/context intent, surface timeout telemetry, and keep backend request bodies aligned with visible UI state
- Claim coverage expansion remains important, but it should follow runtime stability and formalizer-to-prover context transfer rather than run ahead of them

## Sprint status

Sprint window: March 19 – April 2, 2026.

This sprint is nearly complete. The core backend MVP is in place:

- [x] Dockerfile deployment path
- [x] Agentic prover stabilization
- [x] API hardening across the Bundle 4 series
- [x] SSE job streaming for long-running verify calls
- [x] Verification concurrency fix via isolated per-run Lean temp files
- [x] `ProverBackend` abstraction for swappable proving engines
- [x] Deep-trace observability in `runs.jsonl`
- [x] Offline evaluation harness for trace analysis, semantic grading, and uncharted pass@k runs

## Simplification sprint (March 21, 2026)

- [x] Removed classifier as internal formalization gate (classify is now advisory only)
- [x] Cleaned preamble: removed 6 tautological/Mathlib-duplicating files, 22 tautological theorems
- [x] Improved formalizer prompts (NontriviallyNormedField, inline definitions)
- [x] Fixed diagnosis service error logging (actual errors now surfaced)
- [x] Added 429-aware exponential backoff to Leanstral API calls
- [x] Created 32-claim test suite across 4 tiers (`tests/fixtures/claims/test_claims.jsonl`)
- [x] Updated test suite for simplified architecture

## Remaining before sprint close

- [ ] Advisor demo package and walkthrough
- [ ] Frontend reliability integration on top of the v1 API, especially preamble/context preservation and timeout observability
- [ ] Claim coverage expansion after runtime stability and formalizer-to-prover context transfer hardening
- [ ] Final documentation polish for external users and agent builders

## Post-sprint priorities

- [ ] Document-processing microservice for extracting candidate claims from papers
- [ ] Second prover backend, starting with Claude
- [ ] Feed offline evaluation metrics into release and regression gates
- [ ] Pedagogical tutor frontend for explanation and guided interaction
- [ ] LeanEcon / EconLib community contributions and reusable theorem-library work
