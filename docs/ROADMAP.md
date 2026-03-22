# LeanEcon Roadmap

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
- [x] Created 32-claim test suite across 4 tiers (data/test_claims.jsonl)
- [x] Updated test suite for simplified architecture

## Remaining before sprint close

- [ ] Advisor demo package and walkthrough
- [ ] Frontend development on top of the v1 API
- [ ] Claim coverage expansion beyond the current algebraic/preamble-heavy set
- [ ] Final documentation polish for external users and agent builders

## Post-sprint priorities

- [ ] Document-processing microservice for extracting candidate claims from papers
- [ ] Second prover backend, starting with Claude
- [ ] Feed offline evaluation metrics into release and regression gates
- [ ] Pedagogical tutor frontend for explanation and guided interaction
- [ ] LeanEcon / EconLib community contributions and reusable theorem-library work
