# Combobulation

Audit date: March 21, 2026 for repo state, with live endpoint checks run on March 22, 2026 UTC.

Deployment audited: `https://leaneconapi-production.up.railway.app`

## Bottom line

LeanEcon does **not** need a rebuild right now.

It is salvageable and worth hardening in place because the fundamentals are good:

- the public API surface is coherent and matches the deployed OpenAPI schema
- the repo has sensible module boundaries between `api`, `pipeline`, `formalizer`, `lean_verifier`, `agentic_prover`, cache/job state, and MCP runtime glue
- lean-lsp-mcp is already integrated into the proving path, not just sketched in docs

The main problems are not architectural collapse. They are:

1. formalization quality on hard claims
2. weak proving success beyond trivial goals
3. brittle MCP/bootstrap ergonomics
4. uneven test coverage on the riskiest modules
5. stale docs and duplicated fixtures that were making human/AI collaboration harder than it needed to be

If the next round of formalizer/preamble/search improvements still leaves advanced-claim verification near zero, then a deeper redesign becomes reasonable. As of this audit, that threshold has **not** been reached.

## Repo map

- `src/`
  Core service code: FastAPI endpoints, pipeline orchestration, formalization, proving, Lean verification, MCP runtime, caching, metrics, prompts, and preamble library.
- `tests/`
  Pytest suite and fixtures. This is now the canonical home for tracked evaluation/test claim corpora via `tests/fixtures/claims/`.
- `scripts/`
  CLI and maintenance utilities for evals, smoke tests, catalogs, cache seeding, trace analysis, and MCP launching.
- `docs/`
  Primary human docs, API notes, architecture notes, legacy public examples, and skills.
- `lean_workspace/`
  Lean project and preamble modules used by verification and MCP-backed tooling.
- `data/`
  Runtime state only. After cleanup, the only file here is `data/verified_cache.json`.
- `logs/`
  Historical eval reports plus the new production smoke capture under `logs/production_smoke/`.
- `outputs/`
  Generated proof artifacts and stress-test outputs. Useful for debugging, but currently cluttered and not lifecycle-managed.

## What changed in this audit pass

- Moved tracked claim corpora to `tests/fixtures/claims/`.
- Left `data/` as runtime cache state only.
- Deleted duplicate Lean example fixtures from `tests/fixtures/lean_examples/` and pointed verifier tests at `docs/legacy_examples/`.
- Deleted stale `docs/BUILD_LOG.md`.
- Added `scripts/run_lean_lsp_mcp.sh` so MCP uses repo-local writable cache/home paths instead of implicit home-directory `uvx` state.
- Updated `.mcp.json`, docs, and runtime config to use that launcher.
- Added `scripts/production_smoke.py` for live API auditing with timestamps, latencies, payload previews, and job polling.
- Added new tests for:
  - `generate_preamble_catalog.py`
  - `seed_cache.py`
  - `semantic_grader.py`
  - `run_phase1_stress_tests.py`
  - `src/mcp_smoke_test.py`
  - `lean_runner.py`
  - `mcp_runtime.py`
  - `lean_verifier.py` unit paths
  - `explainer.py`
  - `production_smoke.py`
- Removed legacy `main()` / `_run_case()` runner boilerplate from pytest files.
- Updated CI to run lint and non-live pytest on Python `3.11` and `3.13`.
- Synced `.claude/skills/` to the tracked `docs/skills/` copies.
- Regenerated `docs/PREAMBLE_CATALOG.md`.

## Measured status

### Before this pass

These were the baseline facts used for the plan:

- `100` non-live tests passed locally
- total coverage was `54%`
- `ruff check src/ tests/ scripts/` reported `102` issues
- Railway `GET /health` was healthy
- Railway `GET /api/v1/metrics` reported only `1` run
- Railway `GET /api/v1/cache/stats` reported cache size `0`

### After this pass

- non-live pytest: `130 passed, 13 deselected, 2 warnings`
- lint: `All checks passed!`
- combined `src/ + scripts/` coverage: `72%`

Notable remaining warnings:

- FastAPI startup still uses `@app.on_event("startup")`, which now emits a lifespan deprecation warning

### Coverage highlights

Best-covered important paths:

- `src/api.py`: `87%`
- `src/formalizer.py`: `85%`
- `src/lean_runner.py`: `91%`
- `src/mcp_runtime.py`: `66%`
- `src/explainer.py`: `73%`
- `scripts/generate_preamble_catalog.py`: `95%`
- `scripts/production_smoke.py`: `94%`
- `scripts/run_uncharted_evals.py`: `92%`

Still under-covered and still risky:

- `src/pipeline.py`: `41%`
- `src/agentic_prover.py`: `48%`
- `src/proof_file_controller.py`: `45%`
- `src/lean_verifier.py`: `54%`
- `scripts/run_phase1_stress_tests.py`: `57%`

Interpretation: the repo is now much healthier, but the hardest runtime behavior still lives in the lowest-coverage modules.

## Objective assessment

### Test-suite quality and scope

Current grade: `B`

What is good:

- The suite is now pytest-native, discoverable, and materially broader.
- The repo now has direct tests for previously uncovered scripts and low-level wrappers.
- Endpoint behavior, queue/job lifecycle, cache behavior, formalizer branches, and smoke harnesses are all exercised.

What is still weak:

- The most failure-prone logic is still not covered deeply enough: agentic proving, proof-file lifecycle, and the full pipeline retry loop.
- Most of the new safety comes from unit and mocked integration coverage, not from deterministic end-to-end Lean/MCP regression fixtures.
- There is still no serious concurrency/load test for async verify jobs in CI.

Verdict:

The test suite is now respectable and useful for development, but it is not yet strong enough to certify production behavior under realistic proving load.

### Underlying technology reliability

Current grade: `C+`

What is reliable:

- Lean itself is reliable as the final checker.
- The API contract and queue behavior are coherent.
- For trivial claims, the deployed system can classify, formalize, queue, and verify end-to-end.

What is unreliable:

- Advanced-claim formalization remains the dominant failure mode.
- The agentic prover still has very poor success on non-trivial proof obligations.
- Observability appears instance-local or otherwise non-persistent, so `/metrics` and `/api/v1/cache/stats` should not be treated as trustworthy global operational views.

Verdict:

The kernel-checking foundation is solid. The claim-to-proof automation stack above it is still brittle.

### Agentic architecture craftsmanship and efficiency

Current grade: `B-`

Strengths:

- Good separation between classification, formalization, proving, verification, explanation, cache, and job state.
- The agentic prover has real tracing, stop-reason handling, and MCP-backed tool usage.
- The new MCP launcher removes a major ergonomics footgun.

Weaknesses:

- The proving loop is expensive relative to its success rate.
- Historical evals show extremely poor tool-call efficiency on hard claims.
- The formalizer and prover are still too loosely coupled: the prover often has to rediscover context the formalizer already had.

Verdict:

The architecture is crafted by someone who understands the pieces. The efficiency is still not good enough to justify confidence on hard claims.

### API endpoint reliability

Current grade: `B-` for request/response contract, `C+` for operational observability

Local and live schema alignment is good. The deployed API responded as expected on March 22, 2026 UTC:

| Endpoint | UTC start | Latency | Result |
|---|---|---:|---|
| `GET /health` | `2026-03-22T06:28:13.148955+00:00` | `174.6 ms` | `200`, body `{"status":"ok"}` |
| `GET /openapi.json` | `2026-03-22T06:28:13.323620+00:00` | `71.7 ms` | `200`, schema `openapi: 3.1.0` |
| `GET /api/v1/metrics` | `2026-03-22T06:28:13.395941+00:00` | `42.7 ms` | `200`, `total_runs: 1`, `avg_elapsed_seconds: 103.3` |
| `GET /api/v1/cache/stats` | `2026-03-22T06:28:13.438853+00:00` | `35.1 ms` | `200`, `{"size":0}` |
| `POST /api/v1/classify` | `2026-03-22T06:28:13.474027+00:00` | `471.9 ms` | `200`, `ALGEBRAIC` for `raw_claim: "1 + 1 = 2"` |
| `POST /api/v1/formalize` | `2026-03-22T06:28:13.945977+00:00` | `14995.9 ms` | `200`, success, 2 attempts |
| `POST /api/v1/verify` | `2026-03-22T06:28:28.941970+00:00` | `39.9 ms` | `202`, queued |
| `GET /api/v1/jobs/{job_id}` final completion poll | `2026-03-22T06:29:05.790246+00:00` | `38.8 ms` | `200`, completed, verified |

Live payload notes:

- `/formalize` returned a valid theorem stub with `attempts: 2`
- `/verify` returned a job envelope with nested `result`
- the trivial verify job completed successfully with `proof_tactics: "rfl"` and `elapsed_seconds: 34.94911813735962`

Operational caution:

- `/metrics` still reported only one run and `/cache/stats` reported zero cache entries during the live audit, which strongly suggests per-instance or non-persistent observability/cache state
- during harness development, a stricter `30s` request budget timed out on `/formalize`; the endpoint succeeded when rerun with a `90s` client timeout and finished in about `15s`

### lean-lsp-mcp integration depth

Current grade: `B`

What is real today:

- MCP is already used by the prover/runtime layer
- `src/mcp_smoke_test.py` gives a concrete local sanity path
- the repo now has a stable wrapper for MCP process launch

What is missing:

- MCP is still used much more for proof-time diagnostics/goals than for formalization-time search and import discovery
- the system does not yet fully exploit tools like search/completion/goal iteration as a first-class formalization strategy

Verdict:

This is not “fake integration,” but it is still shallow relative to the leverage the toolchain could provide.

### Human-AI collaboration and CI/CD readiness

Current grade: `B+`

What is now good:

- tracked fixtures are in a cleaner place
- canonical legacy examples are not duplicated
- skills are synced with tracked docs
- CI now targets both `3.11` and `3.13`
- pytest and lint now give collaborators a reliable local/CI feedback loop

What still hurts:

- `outputs/` is noisy and not lifecycle-managed
- hidden local settings under `.claude/` remain partly outside tracked collaboration policy
- the repo still depends heavily on human judgment for eval interpretation and artifact cleanup

Verdict:

The repository is now substantially better set up for iterative human/AI collaboration, especially for CI and local validation. It is not yet polished into a low-noise ops environment.

## Eval report summary

### `logs/eval_reports/20260321T212004Z`

This is a raw uncharted-eval run on 5 advanced claims.

- formalization robustness: `0.2`
- verified cases: `0`
- semantic alignment average: `4.0` across the one claim that formalized
- tool-call efficiency: `15/202 = 7.4%`

Dominant failure signatures:

- bad import/module resolution
- unknown identifiers like `StrictConcave` and `hessian`
- unsolved-goal churn on the one claim that did formalize

### `logs/eval_reports/20260321T233736Z`

This is another raw uncharted-eval run on the same 5 advanced claims.

- formalization robustness: `0.2`
- verified cases: `0`
- semantic alignment average: `4.0`
- tool-call efficiency: `2/150 = 1.3%`

Dominant failure signatures shifted toward:

- Bellman-operator type mismatch
- `NontriviallyNormedField` synthesis failures
- repeated existential-goal failures on Solow-style claims

Interpretation:

The top-line results matched run 1, but the specific error families moved around. That points to fragile prompting and theorem-shape dependence rather than one single deterministic blocker.

### `logs/eval_reports/20260322T034844Z`

This is **not** a raw uncharted-eval output. It is a prior audit/meta-report summarizing:

- the two earlier uncharted runs
- `21` pipeline runs from `logs/runs.jsonl`
- broader architecture and process observations

Its quantitative headline is still useful:

- formalization robustness: `0.2`
- verified cases: `0`
- semantic alignment average: `4.0`

But it should be treated as a prior analyst’s synthesis, not as a primary raw experiment artifact.

## Script inventory

Every file in `scripts/`, plus the MCP smoke test entry point:

- `scripts/analyze_traces.py`
  Reads `logs/runs.jsonl` and renders aggregate agentic-trace metrics in text and/or JSON form.
- `scripts/generate_preamble_catalog.py`
  Generates `docs/PREAMBLE_CATALOG.md` directly from `src/preamble_library.py`.
- `scripts/production_smoke.py`
  Runs a tiny live smoke test against a deployed LeanEcon API, capturing UTC timestamps, latencies, payload previews, and verify-job polling.
- `scripts/run_lean_lsp_mcp.sh`
  Repo-owned launcher for `lean-lsp-mcp` that forces writable local `HOME`/XDG/UV cache paths under `.tmp/lean-lsp-mcp`.
- `scripts/run_phase1_stress_tests.py`
  Runs the advanced raw-Lean stress-suite, validates each case with both MCP and compiler checks, then executes the isolated pipeline and writes artifacts plus a markdown summary.
- `scripts/run_uncharted_evals.py`
  Drives pass@k uncharted evaluations from a JSONL claim corpus, bypassing the classifier gate and writing results plus markdown reports.
- `scripts/seed_cache.py`
  Pre-seeds the verified-result cache from curated passing examples in `docs/legacy_examples/`.
- `scripts/semantic_grader.py`
  CLI wrapper around semantic-alignment grading for one theorem pair or a JSONL batch.
- `src/mcp_smoke_test.py`
  Local sanity test for the MCP plumbing: env loading, tool registration, raw diagnostic queries, and goal extraction against a dedicated Lean fixture.

## High-ROI quick wins

1. Persist metrics and cache state outside the Railway instance.
   Right now `/metrics` and `/cache/stats` do not look trustworthy as system-wide telemetry.

2. Move FastAPI startup from `on_event` to lifespan handlers.
   This is small and removes the remaining test-time deprecation warning.

3. Add search-first formalization support.
   The biggest ROI is to let the formalizer consult MCP/Mathlib search before emitting imports and identifiers.

4. Expand the preamble library specifically for repeated failure families.
   The logs keep pointing at the same kinds of gaps: fixed-point, concavity/Hessian-style analysis, richer optimization, and dynamic programming.

5. Add persistent artifact hygiene.
   `outputs/` and historical debug artifacts should either rotate, archive, or move behind a dedicated artifact policy.

6. Add one deterministic end-to-end Lean/MCP regression lane in CI.
   The repo is much healthier locally, but the hard runtime path still needs a stable integration gate.

## Medium-term recommendations

1. Decouple formalization and proving with a typed intermediate representation.
   The prover should inherit more structure than a raw theorem string and a hope.

2. Make MCP a first-class formalization assistant, not just a proving-time helper.
   Use tool-backed import discovery, symbol lookup, and quick compile checks before the proving loop starts.

3. Replace instance-local job/cache/metrics assumptions with shared infra.
   If LeanEcon is meant to be used seriously, queue state and observability should not depend on one container’s memory and filesystem.

4. Invest in targeted agentic-proof benchmarks.
   Right now the prover is expensive and weak on exactly the goals that matter. That should become a measurable benchmark set, not just a qualitative complaint.

5. Consider a deeper redesign only if these focused changes fail.
   Rebuild if, after formalizer-search improvements and stronger shared state, the system still cannot move beyond trivial verified goals. Rebuild is not the right first move today.

## Final verdict

LeanEcon is a promising system with a real product shape, real automation, and now a meaningfully healthier repository.

The hard truth is that the **formalizer and prover are still not strong enough for advanced economics claims**. The good news is that the repo structure is already good enough to improve that without starting over.

My recommendation is:

- do **not** rebuild now
- keep hardening in place
- prioritize formalization search, preamble coverage, and persistent ops state
- reevaluate the architecture only if those targeted interventions still leave advanced-claim success near zero
