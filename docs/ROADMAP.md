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

## Remaining before sprint close

- [ ] Advisor demo package and walkthrough
- [ ] Frontend development on top of the v1 API
- [ ] Claim coverage expansion beyond the current algebraic/preamble-heavy set
- [ ] Final documentation polish for external users and agent builders

## Post-sprint priorities

- [ ] Document-processing microservice for extracting candidate claims from papers
- [ ] Second prover backend, starting with Claude
- [ ] Pedagogical tutor frontend for explanation and guided interaction
- [ ] LeanEcon / EconLib community contributions and reusable theorem-library work
