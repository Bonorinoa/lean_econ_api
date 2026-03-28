---
name: leanecon-api
description: "Integration guide for the LeanEcon formal verification API. Use whenever building frontends, dashboards, eval harnesses, or services connecting to LeanEcon for mathematical claim verification. Triggers on: UI for theorem verification, SSE streaming, async job polling, classify/formalize/verify workflows, test suites, formalization debugging, observability logs, or dashboards combining LeanEcon endpoints. Also trigger on mentions of LeanEcon, preamble library, EconLib, verification dashboard, evaluation harness, or 'test the API' / 'build a dashboard' in this project context."
---

# LeanEcon API Integration Skill

LeanEcon is a headless formal verification microservice that takes mathematical claims (natural language, LaTeX, or raw Lean 4) and produces machine-checked proofs using Lean 4 and Mathlib.

> LeanEcon v1 is in maintenance-only mode. Active development has moved to
> `https://github.com/Bonorinoa/leanecon_v2`.

**Base URL:** `https://leaneconapi-production.up.railway.app`
**Interactive docs:** `{BASE_URL}/docs` (Swagger UI)
**OpenAPI schema:** `{BASE_URL}/openapi.json`
**Source of truth:** [`src/api.py`](../../src/api.py), [`docs/API.md`](../API.md),
[`docs/HARNESS_FORMALIZER_PROVER_REPORT.tex`](../HARNESS_FORMALIZER_PROVER_REPORT.tex),
and the live `/openapi.json`.

## Architecture overview

LeanEcon has a three-layer trust model that frontends should communicate to users:

1. **Stochastic layer** — Leanstral (LLM) generates candidate formalizations and proofs. May fail. Output quality varies.
2. **Human-in-the-loop** — The user reviews the formalized theorem before proving. This is where frontends add value.
3. **Deterministic layer** — Lean 4's kernel verifies the proof from axioms. If it passes, it's mathematically certified. Not LLM confidence — formal certainty.

## Core workflow (6 steps + optional compile check)

Every frontend should implement this sequence:

```
1. POST /api/v1/classify    → (OPTIONAL) Advisory scope check + preamble suggestions
2. POST /api/v1/formalize   → Get a Lean theorem stub (with sorry). Pass preamble_names if needed.
3. [User reviews/edits]     → Frontend presents theorem for review
4. OPTIONAL: POST /api/v1/lean_compile → Direct local Lean compile/debug check for complete Lean files
5. POST /api/v1/verify      → Returns 202 + job_id (async)
6. GET /api/v1/jobs/{id}/stream  → SSE progress events
   GET /api/v1/jobs/{id}         → Final result when complete
7. POST /api/v1/explain     → Natural language explanation (optional)
```

> **Important:** Classification is no longer an internal gate for formalization.
> The formalizer attempts all claims directly. Use `/classify` for frontend UX
> (scope hints, preamble suggestions) but you can skip it and go straight to
> `/formalize`. Preamble injection is opt-in via explicit `preamble_names`.
>
> **Optional debug path:** If you already have complete Lean code and want a
> direct kernel/compiler check without proving, use `/api/v1/lean_compile`.
> That endpoint is synchronous, local-only, and best treated as a debugging or
> preflight primitive rather than the default product path.
>
> **Also important:** `/verify` is queue-based and concurrency-safe. LeanEcon no
> longer routes verification through a shared `LeanEcon/Proof.lean`; proving and
> final verification use isolated per-run temp files. The job-status response
> now also includes additive observability metadata such as queue/start/finish
> timestamps and the latest reported pipeline stage.

## Current measured reality (2026-03-28)

Use these numbers instead of older March 22-24 placeholders:

- Local non-live pytest: `253 passed, 13 deselected`
- Local MCP smoke:
  `./leanEconAPI_venv/bin/python src/mcp_smoke_test.py`
  exited `0` on 2026-03-28
- Production smoke gate:
  `./leanEconAPI_venv/bin/python scripts/production_smoke.py --base-url https://leaneconapi-production.up.railway.app --poll-interval 1 --max-polls 10`
  exited `0` on 2026-03-28 with `summary.overall_ok = true`
- `lake build` in `lean_workspace`: successful
- Tier 1 selected full benchmark:
  `benchmarks/reports/tier1_core_selected_full_full_20260328T181026Z.md`
  shows:
  - `raw_claim -> full API`: `pass@1 = 0.000`
  - `theorem_stub -> verify`: `pass@1 = 1.000`
  - `raw_lean -> verify`: `pass@1 = 1.000`
- Tier 1 core formalizer-only benchmark:
  `benchmarks/reports/tier1_core_formalizer_only_20260328T174455Z.md`
  shows:
  - `raw_claim -> formalizer-only gate`: `pass@1 = 0.667`
  - semantic `>=4` rate: `0.750`
- Tier 2 frontier formalizer-only benchmark:
  `benchmarks/reports/tier2_frontier_formalizer_only_20260325T065620Z.md`
  shows:
  - `raw_claim -> formalizer-only gate`: `pass@1 = 0.667`
  - semantic `>=4` rate: `1.000`
  - the extreme-value repair case still fails

Interpretation:

- Theorem-stub verification and raw Lean verification remain the strongest
  release paths.
- Natural-language formalization is still mixed on the bounded Tier 1 core
  slice.
- Full raw-claim end-to-end verification is still the weakest public lane.
- Frontier natural-language formalization is still mixed.
- The live service can lag branch-local fixes. Treat the production smoke gate
  as the deploy truth source.

## Endpoint reference

### POST /api/v1/classify

Determines whether a claim is in scope, whether it looks Mathlib-native, and which preamble modules match.

**Request:**
```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion equals gamma"
}
```

**Response:**
```json
{
  "category": "DEFINABLE",
  "formalizable": true,
  "reason": "Uses CRRA utility which is defined in the preamble library",
  "preamble_matches": ["crra_utility"],
  "auto_preamble_matches": ["crra_utility"],
  "suggested_reformulation": null,
  "definitions_needed": null,
  "error_code": "none"
}
```

**Categories and frontend actions:**

| `category` | `formalizable` | Frontend action |
|---|---|---|
| `RAW_LEAN` | `true` | Skip formalize, go straight to verify |
| `ALGEBRAIC` | `true` | Proceed to formalize normally |
| `MATHLIB_NATIVE` | `true` | Proceed to formalize normally; expect direct Mathlib imports rather than preamble matches |
| `DEFINABLE` | `true` | Show `preamble_matches`, proceed to formalize with those preamble names |
| `REQUIRES_DEFINITIONS` | `false` | Show rejection reason, suggest reformulation |

Note: The classifier includes rescue logic. If the LLM says `REQUIRES_DEFINITIONS` but keyword matching finds preamble entries, it gets rescued to `DEFINABLE`. Likewise, if the LLM says `MATHLIB_NATIVE` but a bundled preamble match exists, it is upgraded to `DEFINABLE`.
Use `preamble_matches` as the broader advisory set and `auto_preamble_matches`
as the backend's bounded default if the user does not choose explicitly.

### POST /api/v1/formalize

Generates a Lean 4 theorem stub with `sorry` placeholder.

**Request:**
```json
{
  "raw_claim": "Cobb-Douglas output elasticity equals alpha",
  "preamble_names": ["cobb_douglas_2factor"]
}
```

**Response (success):**
```json
{
  "success": true,
  "theorem_code": "import Mathlib\nimport LeanEcon.Preamble.Producer.CobbDouglas2Factor\n\ntheorem cobb_douglas_elasticity ...\n  := by sorry",
  "attempts": 1,
  "errors": [],
  "formalization_failed": false,
  "failure_reason": null,
  "error_code": "none",
  "preamble_used": ["cobb_douglas_2factor"],
  "diagnosis": null,
  "suggested_fix": null,
  "fixable": null
}
```

**Response (failure after retries):**
```json
{
  "success": false,
  "theorem_code": "...",
  "attempts": 3,
  "errors": ["unknown identifier `StrictConcave`"],
  "formalization_failed": false,
  "failure_reason": null,
  "error_code": "formalization_failed",
  "preamble_used": [],
  "diagnosis": "The formalizer attempted to use StrictConcave which is not directly available",
  "suggested_fix": "Use ConcaveOn from Mathlib.Analysis.Convex.Basic instead",
  "fixable": true
}
```

The formalizer uses up to 2 model calls and 3 validations, with compiler
feedback and deterministic repairs between attempts.
`formalization_failed=true` is reserved for explicit out-of-scope rejections; a
compile failure after retries can still return `formalization_failed=false`
alongside `diagnosis`, `suggested_fix`, and `fixable`.

Current implementation details:
- The formalizer now builds bounded retrieval context before the first model call.
- If `preamble_names` is omitted, it may auto-select matching preamble modules.
- Auto-preamble selection is now keyword-ranked and capped, which reduces noisy
  cross-domain imports on simple economics claims.
- The runtime formalize path now turns bounded MCP retrieval on by default and
  uses `lean_local_search` / `lean_loogle` as a first-class retrieval assistant
  when the MCP path is healthy.
- The theorem name is deterministically uniquified before validation so
  generated stubs do not collide with imported declarations.
- Repair is compiler-bucketed: import/module, identifier, typeclass, syntax, or
  semantic mismatch.
- The returned `formalization_context` now carries selected preambles,
  candidate imports/identifiers, MCP hits, and a bounded
  `runtime_search_plan` for downstream `/verify`.
- If MCP is unhealthy, the formalizer skips runtime retrieval and relies on
  curated hints plus local compilation.

### POST /api/v1/lean_compile

Compiles a complete Lean file directly with the local Lean toolchain. This
bypasses both formalization and the agentic prover.

**Request:**
```json
{
  "lean_code": "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  norm_num\n",
  "filename": "one_plus_one.lean",
  "check_axioms": false
}
```

**Response:**
```json
{
  "success": true,
  "errors": [],
  "warnings": [],
  "stdout": "",
  "stderr": "",
  "verification_method": "lake_env_lean",
  "elapsed_ms": 421.7,
  "axiom_info": null,
  "telemetry": {
    "endpoint": "lean_compile",
    "model": "local_lean_compiler",
    "usage_present": false,
    "local_only": true,
    "estimated_cost_base_usd": null,
    "estimated_cost_stress_usd": null
  }
}
```

Use this when:
- the user already has complete Lean code
- you want fast compiler/kernel diagnostics
- you want to debug a formalized theorem before spending time on `/verify`

Do not use this as a replacement for `/verify`. It does not generate proofs, it
does not queue a job, and Lean files containing `sorry` will fail.

### POST /api/v1/verify

Submits a theorem for agentic proving. **This is async — returns immediately with a job ID.**

**Request:**
```json
{
  "theorem_code": "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by sorry",
  "explain": false,
  "preamble_names": ["crra_utility"],
  "formalization_context": {
    "schema_version": 1,
    "selected_preambles": ["crra_utility"]
  },
  "reasoning_preset": "medium",
  "budget_overrides": {
    "wall_clock_timeout_seconds": 180,
    "append_round_cap": 24
  }
}
```

`/api/v1/verify` currently accepts:
- `theorem_code`
- `explain`
- `preamble_names`
- `formalization_context`
- `reasoning_preset`
- `budget_overrides`

`pass_k` is part of the offline eval harness, not the public verify endpoint.

**Response (HTTP 202):**
```json
{
  "job_id": "abc123-def456",
  "status": "queued"
}
```

The proof often takes 30-180 seconds on straightforward verify lanes and can be
much slower on hard raw-claim cases. You MUST either poll or stream — never
block the UI.
For the fastest user-facing flow, keep `explain=false` on `/verify` and call
`POST /api/v1/explain` only after the verify job completes.

### GET /api/v1/jobs/{job_id}/stream

SSE stream of progress events. Preferred over polling.

```javascript
const eventSource = new EventSource(`${BASE_URL}/api/v1/jobs/${jobId}/stream`);

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === "progress") {
    // Typical stages: "cache", "formalize", "agentic_init",
    // "agentic_fast_path", "agentic_setup", "agentic_run", "explain"
    // data.message: human-readable progress text
    // data.status: "running" | "done" | "error"
    return;
  }
  
  if (data.type === "complete") {
    eventSource.close();
    // Fetch full result: GET /api/v1/jobs/${jobId}
  }
};

eventSource.onerror = () => {
  eventSource.close();
  // Fall back to polling GET /api/v1/jobs/{jobId} every 2-3 seconds
};
```

SSE events do NOT include the final verification payload. After `type: "complete"`, fetch the full job result.

### GET /api/v1/jobs/{job_id}

Returns a job envelope. The final verify payload lives under `result`.

**Response:**
```json
{
  "job_id": "abc123-def456",
  "status": "running",
  "queued_at": "2026-03-28T16:04:19.536923+00:00",
  "started_at": "2026-03-28T16:04:19.538734+00:00",
  "finished_at": null,
  "last_progress_at": "2026-03-28T16:04:19.552935+00:00",
  "current_stage": "agentic_fast_path",
  "stage_timings": {
    "agentic_init": 0.8392333984375
  },
  "result": null,
  "error": null
}
```

**Phase values and UI treatment:**

| `phase` | Meaning | UI treatment |
|---|---|---|
| `verified` | Lean kernel accepted the proof | Green indicator. Machine-checked proof. |
| `proved` | Proof generated but Lean rejected it | Warning. Prover tried but proof had a flaw. Offer retry. |
| `failed` | No valid proof found | Failure. Check `formalization_failed` to distinguish formalization vs proving failure. |

### POST /api/v1/explain

Generates natural language explanation of any pipeline result. Can accept verification, formalization, or classification results.

**Request:**
```json
{
  "original_claim": "CRRA utility has constant relative risk aversion",
  "theorem_code": "theorem crra_rra ...",
  "verification_result": { "success": true, "lean_code": "..." }
}
```

### Operational endpoints

- `GET /health` → `{"status": "ok"}`
- `POST /api/v1/lean_compile` → Synchronous local Lean compile/debug check
- `GET /api/v1/metrics` → Aggregate verification stats from the JSONL eval log
- `GET /api/v1/benchmarks/latest` → Latest summary-only offline benchmark snapshot
- `GET /api/v1/cache/stats` → `{"size": N}`
- `DELETE /api/v1/cache` → Clear verified result cache

Runtime state lives in repo-local paths by default. When `LEANECON_STATE_DIR`
is set, the JSONL run log moves to `${LEANECON_STATE_DIR}/logs/runs.jsonl` and
the verified-result cache moves to `${LEANECON_STATE_DIR}/data/verified_cache.json`.
Benchmark snapshots now follow the same runtime pattern: the API prefers
`${LEANECON_STATE_DIR}/benchmarks/snapshots/*.json` when present, then falls
back to the bundled `benchmarks/snapshots/*.json` copied into the image.
The benchmark status endpoint intentionally excludes per-claim details; read the
snapshot JSON files directly when you need case-level internals. If neither
location has any snapshot artifacts yet, `GET /api/v1/benchmarks/latest` can
honestly return `404`.

## Critical integration patterns

### The async verify pattern

**This is the #1 source of frontend bugs.** Verify is NOT synchronous.

```
POST /api/v1/verify → HTTP 202 { "job_id": "...", "status": "queued" }
```

NEVER block the UI waiting for verify to return. Show a progress timeline.

### Preamble-aware formalization

When classify returns `preamble_matches`, pass them to formalize:

```json
POST /api/v1/formalize
{
  "raw_claim": "Cobb-Douglas output elasticity equals alpha",
  "preamble_names": ["cobb_douglas_2factor"]
}
```

LeanEcon currently ships 23 preamble entries across 8 areas: consumer,
producer, risk, dynamic, macro, optimization, welfare, and game theory. For UI
pickers or product copy, read [`docs/PREAMBLE_CATALOG.md`](../PREAMBLE_CATALOG.md)
instead of hardcoding module names or counts in multiple places.

For theorem-library or Explore-to-Pipeline handoffs, preserve
`preamble_names` alongside the claim text. Sending only the natural-language
claim can silently drop crucial theorem context and reduce formalization
reliability.

Also preserve `formalization_context` from `/formalize` into `/verify`
unchanged. That handoff now includes the formalizer's retrieval notes, MCP
hits, and suggested runtime search queries for the prover. If you also send
`preamble_names` to `/verify`, they must exactly match
`formalization_context.selected_preambles`.

### Axiom soundness

When verification succeeds, check `axiom_info`:

- `sound: true` + `has_sorry_ax: false` = fully verified from axioms
- `has_sorry_ax: true` = proof is NOT sound despite compilation (show warning)
- `nonstandard_axioms` lists anything beyond the standard three (`propext`, `Classical.choice`, `Quot.sound`)
- `axiom_info: null` means axiom metadata was unavailable or intentionally skipped; treat it as "not available," not as verification failure

### Error codes

Every response includes `error_code` for programmatic error handling:

- `none` — Success
- `invalid_input` — Request payload was blank or malformed
- `classification_rejected` — Claim needs definitions not in scope
- `classification_failed` — Classifier crashed unexpectedly
- `formalization_failed` — Could not produce valid Lean
- `formalization_timeout` — Formalization timed out
- `formalization_unformalizable` — Claim is out of Mathlib scope
- `proof_not_found` — Valid theorem, no proof found
- `proof_timeout` — Prover timed out (check `partial`, `success`, and `stop_reason` together)
- `verification_rejected` — Lean rejected the proof
- `verification_sorry` — Proof contains sorry
- `internal_error` — Unexpected server-side failure

## Observability and data flywheel

### runs.jsonl — the evaluation log

Every verification run appends a structured JSON line to `logs/runs.jsonl` by
default, or to `${LEANECON_STATE_DIR}/logs/runs.jsonl` when `LEANECON_STATE_DIR`
is set. This is the source of truth for metrics and offline evaluation. Each
entry includes: claim text, classification result, formalization result,
verification result, tool call counts, timing, errors, axiom info, and
provider telemetry with conservative cost estimates when real usage payloads
exist.

The `/api/v1/metrics` endpoint aggregates this log into summary statistics. For deeper analysis, process `runs.jsonl` directly.

Important telemetry caveats:

- provider telemetry is observability metadata, not billing output
- estimated cost fields stay `null` when provider usage is incomplete
- `/api/v1/lean_compile` is tagged as local-only and excluded from LLM spend
- benchmark and product copy should not imply Leanstral is stably free

Cache hits are intentionally logged too so `/api/v1/metrics` reflects real
operational traffic. When you analyze proof quality or tool efficiency, exclude
`from_cache` entries so cache replays do not dilute tactic-depth or tool-waste
metrics.

### Building feedback loops

The data flywheel works like this:

1. **Run claims** through the pipeline (test suite, interactive use, or eval harness)
2. **Collect traces** in `runs.jsonl` (automatic)
3. **Analyze failures** — which layer failed? Classification? Formalization? Proving?
4. **Improve prompts** — the classifier and formalizer system prompts in `formalizer.py`
5. **Re-run and compare** — track metrics across iterations, especially by lane

For dashboards: fetch `/api/v1/metrics` for aggregate stats, parse the
configured JSONL run log for per-claim drill-down, and use the additive job
metadata from `GET /api/v1/jobs/{job_id}` to show queue time, current stage,
and `stage_timings`. `current_stage` now prefers the most specific active stage
instead of being overwritten by a later wrapper-stage completion event.

## Evaluation harness

### run_uncharted_evals.py

The offline evaluation script is now stage-aware. It can mix:

- formalization-only cases
- prover-only cases from `theorem_code` / `preformalized_theorem`
- full end-to-end cases

Cheap day-to-day benchmark:

```bash
./leanEconAPI_venv/bin/python scripts/run_uncharted_evals.py \
  tests/fixtures/claims/test_claims.jsonl \
  --profile ci
```

Explicit frontier probe:

```bash
./leanEconAPI_venv/bin/python scripts/run_uncharted_evals.py \
  tests/fixtures/claims/uncharted_claims.jsonl \
  --profile frontier \
  --pass-k 1 \
  --limit 2
```

Treat `uncharted_claims.jsonl` as a frontier-diagnostics harness, not the
default CI benchmark. For current public-facing frontier claims, prefer the
tracked `tier2_frontier` benchmark artifacts. The latest completed
formalizer-only report on 2026-03-25 shows `pass@1 = 0.667`, with contraction
mapping and monotone-sequence convergence compiling while the
extreme-value/strict-concavity repair case still fails.

**Profiles:**
- `ci` — cheap default; `pass@1`, no semantic grading, dataset-driven staging
- `core` — same staged flow, but adds semantic grading
- `frontier` — restores high-cost end-to-end probing with retry-friendly defaults

**Dataset behavior in `dataset` stage mode:**
- `expect: verify` runs formalization plus proving
- `expect: formalize` stops after formalization
- `expect: fail_gracefully` also stops after formalization and checks harness stability
- `theorem_code` / `preformalized_theorem` triggers prover-only evaluation
- unlabeled raw-claim rows still default to full end-to-end evaluation

**Input format**:
```json
{"id": "arith_001", "raw_claim": "1 + 1 = 2", "expect": "verify", "tags": ["tier1"]}
{"id": "calc_001", "raw_claim": "A continuous function on [a,b] attains its maximum", "expect": "formalize", "tags": ["tier2"]}
{"id": "proof_001", "raw_claim": "1 + 1 = 2", "theorem_code": "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  sorry", "eval_stage": "prove"}
```

**Output artifacts:**
- `case_records.jsonl` — one record per completed benchmark case
- `results.json` — full run summary plus embedded case records
- `report.md` — readable markdown report

**Output metrics (per claim):**
- `evaluation_stage` — `formalization`, `prove`, or `e2e`
- `expected_outcome` / `expectation_met` — benchmark-target labeling for honest staged scoring
- `formalization_success` — did the formalizer produce Lean that compiles with `sorry`?
- `pass_k_success` — did at least one proving attempt verify?
- `semantic_score` — LLM-graded fidelity of formalization to original claim (1-5) when enabled
- `tool_call_efficiency` — successful tactic applications / total tool calls
- `tool_call_waste_ratio` — complement of efficiency, useful for spotting expensive loops
- `blocked_tool_calls` — calls cut off by search budgets, duplicate-read checks, or loop guards
- `tactic_depth` — proof complexity measure

**Aggregate metrics:**
- `Formalization Robustness` — fraction of cases that ran formalization and succeeded
- `Agentic Proving Power` — fraction of proof-stage cases verified at pass@k
- `Expectation Benchmark Score` — fraction of labeled benchmark targets met
- `Semantic Alignment` — average semantic score across graded claims
- `Tool Call Efficiency` / `Tool Call Waste Ratio` — global proof-stage efficiency measures
- `Global Error Frequency` — most common Lean errors across proof attempts

### run_benchmark.py

Use this when you want the lighter benchmark foundation for a research preview,
with explicit lane separation, semantic grading for raw-claim lanes, per-tier
aggregation, and stable snapshot/report artifacts.

```bash
./leanEconAPI_venv/bin/python scripts/run_benchmark.py \
  benchmarks/tier0_smoke.jsonl \
  --repetitions 3 \
  --no-cache
```

Fast formalizer-only gate:

```bash
./leanEconAPI_venv/bin/python scripts/run_benchmark.py \
  benchmarks/tier1_core.jsonl \
  --mode formalizer-only
```

Focused formalizer regression gate:

```bash
./leanEconAPI_venv/bin/python scripts/run_benchmark.py \
  benchmarks/formalizer_regressions.jsonl \
  --mode formalizer-only
```

Recommended benchmark files:
- `benchmarks/tier0_smoke.jsonl` — release smoke gate for arithmetic, direct-hypothesis reuse, and one-step preamble basics
- `benchmarks/tier1_core.jsonl` — release gate for core preamble-backed economics identities
- `benchmarks/tier2_frontier.jsonl` — acceptance-only Mathlib-native or search-heavy claims
- `benchmarks/formalizer_regressions.jsonl` — focused regression slice with real `tier` values plus regression tags

**Lanes:**
- `raw_claim -> full API`
- `theorem_stub -> verify`
- `raw_lean -> verify`

**Artifacts:**
- `benchmarks/snapshots/*.json`
- `benchmarks/reports/*.md`

**Tracked metrics:**
- `pass@1` as the primary product metric
- `pass@3` as the main retry/internal metric
- `pass@5` when repetitions are at least 5
- `p50` / `p95` latency
- `partial_attempts` / `partial_rate` so interrupted-but-usable runs are visible
- `failure_stage`, `error_code`, and `stop_reason`
- `validation_method_counts`, `validation_fallback_reason_counts`, `repair_bucket_counts`, and `retrieval_source_counts`
- semantic-alignment grading on `raw_claim` lanes
- additive `summary.by_tier` aggregates in snapshot and `/api/v1/benchmarks/latest`

Cache is disabled by default so benchmark runs are not flattered by warm
verified-result replays.

### Designing test claims

Test claims should span these categories:

**Tier 0 — Smoke gate:**
Arithmetic, exact-hypothesis reuse, and one-step preamble definitions that should pass at very high rates.
- "1 + 1 = 2"
- Budget constraint equalities
- Budget-set membership from a direct inequality hypothesis

**Tier 1 — Core release gate:**
Preamble-backed economics identities where the system has a real baseline and should clear product targets.
- "Under CRRA utility, relative risk aversion equals gamma"
- "Cobb-Douglas output elasticity w.r.t. capital equals alpha"
- "Marshallian demand for good 1 is alpha * m / p1"
- "The New Keynesian Phillips Curve identity"

**Tier 2 — Frontier acceptance:**
Claims that test Mathlib-native retrieval or deeper search. Track them honestly, but do not market them as the shipping baseline.
- Fixed-point theorems (Banach, Brouwer)
- Monotone-sequence convergence
- Hessian/second-order conditions

**Out-of-scope rejection set:**
Claims the classifier should route to `REQUIRES_DEFINITIONS`.
- "Nash equilibrium exists in finite games"
- General equilibrium existence
- Claims requiring definitions not in Mathlib or the preamble

### Known failure patterns from evaluation

The failure picture is split across layers. Tier 1 core release slices are now
meaningfully stronger than frontier natural-language cases. Do not assume
either "formalization is always the problem" or "the prover is the main
bottleneck"; the answer depends heavily on the lane and tier.

1. **Hallucinated Mathlib paths and theorem names.** The formalizer or prover guesses identifiers such as `StrictConcaveOn.neg_deriv2` or `StrictConcaveOn.contDiff_iff_deriv2_nonpos` that do not exist. Fix: verify identifiers with search before committing to them, and add search-assisted import/name discovery during formalization.

2. **Strict concavity and power notation are brittle failure surfaces.** A
   recurring formalizer mistake is to emit bare `StrictConcave` when Mathlib
   needs `StrictConcaveOn` or `ConcaveOn`. Real-power claims also drift into
   brittle `Real.rpow` formulations when a natural-exponent `x ^ n` statement
   would be simpler and easier to prove.

3. **Type class and calculus API mismatches.** Claims about derivatives, Hessians, normed spaces, or product spaces still trigger `failed to synthesize instance`, `Unknown constant`, or function-shape mismatches. The model often reaches for one-dimensional `deriv` lemmas on higher-dimensional `fderiv` goals.

4. **Context blow-up on long hard attempts.** Large `tool_trace` and retry
   histories still need aggressive caps. That remains especially relevant for
   frontier proving loops and search-heavy repair cycles.

5. **Guardrails help, but do not solve frontier math.** Duplicate read-only query blocking, search budgets, and total tool budgets now stop some high-waste loops early. That saves cost, but it also means frontier eval failures often end as honest "stopped before burning more budget" results rather than full theorem attempts.

6. **Use staged evals for honest routine measurement.** For regular progress tracking, prefer:
   - formalization-only evals
   - prover-only evals on preformalized theorem stubs
   - MCP smoke tests
   - small end-to-end `pass@1` regressions
   Keep `uncharted` pass@k runs for explicit capability probes.

## UX best practices

### What to show during the 30-180s verification wait

Map SSE `stage` values to user-friendly labels:

| `stage` | User-facing label |
|---|---|
| `parse` | "Cleaning and parsing the claim..." |
| `formalize` | "Translating to formal mathematics..." |
| `prover_dispatch` | "Queueing the proving run..." |
| `agentic_init` | "Setting up the proof environment..." |
| `agentic_setup` | "Connecting to Lean 4..." |
| `agentic_run` | "Searching for a proof..." |
| `agentic_check` | "Checking proof progress..." |
| `agentic_verify` | "Verifying with Lean 4 kernel..." |
| `cache` | "Checking cached results..." |
| `explain` | "Generating explanation..." |

### Claim input UX

Support three input modes:
1. **Natural language** — "Under CRRA utility, relative risk aversion equals gamma"
2. **LaTeX** — "$-c \cdot u''(c)/u'(c) = \gamma$"
3. **Raw Lean 4 theorem stub** — Full `.lean` file content with `import Mathlib` and `:= by sorry`
4. **Complete Lean 4 file** — Ready-to-compile Lean code for `/api/v1/lean_compile`

Raw Lean input is detected automatically by classify (returns `RAW_LEAN`) and
bypasses formalization. If the file still contains `sorry`, route it to
`/verify`; if it is already complete Lean code, `/lean_compile` is the faster
debug path.

### The review step matters

After formalize returns `theorem_code`, ALWAYS show it to the user before calling verify. This is the human-in-the-loop layer. The user should confirm "yes, that's what I meant" before spending 30-120s on proving.

### Partial results and timeouts

If `partial: true` in the result, the prover timed out but returned its best
effort. Show the partial proof with a "Timed out — retry?" option. The
`stop_reason` field explains why. Recent builds also normalize low-level anyio
cancel-scope wording so product UIs see a stable interruption warning instead
of a raw runtime-internals message.

If the final result has `success: true`, `phase: "verified"`, and
`partial: false`, treat it as fully verified even if `warnings` mentions an
interruption or timeout cleanup path. Do not show a `Partial (timeout)` badge
based only on warning text.

## Dashboard patterns

For building a dashboard that interacts with each endpoint separately and supports custom workflows:

### Single-endpoint interaction

Each endpoint should have its own panel or tab with:
- Input form (claim text, optional preamble names, optional parameters)
- Raw request/response display (collapsible JSON)
- Formatted result display (status badges, error highlighting, theorem code with syntax highlighting)

### Custom workflow builder

Allow users to chain endpoints in sequence:
```
classify → formalize → [review] → lean_compile (optional) → verify → explain
```

Or in an agentic loop:
```
classify → formalize → verify → [if failed] → formalize (with diagnosis) → verify → ...
```

The dashboard should:
- Pass outputs from one step as inputs to the next automatically
- Show the full pipeline state at each step
- Allow manual override at any step (edit the theorem code before verifying)
- Log all interactions to enable replay and analysis

### Batch mode

For test suites, support batch submission:
- Upload a JSONL file of claims
- Run each through the full pipeline
- Display a summary table with per-claim results
- Export results as a report (markdown or JSON)

## Limitations to communicate honestly

- **Raw Lean is still the best product path.** It is faster, more reliable, and
  has the cleanest semantics today.
- **Theorem-stub verification is also strong.** If you can get a clean theorem
  stub from a human or another tool, `/verify` is currently a strong lane.
- **Formalization is much better on bounded release tiers than on frontier claims.**
  Tier 1 core now measures well, but frontier natural-language cases are still
  mixed.
- **Formalization is now search-assisted but still bounded.** LeanEcon uses
  preamble matching, curated import/identifier hints, bounded MCP retrieval,
  and compiler-bucketed repair before spending more model calls. This improves
  reliability, but it is still not an open-ended proving loop.
- **Verification is stochastic.** The same claim may pass on one run and fail on the next. Offer retry buttons.
- **Currently strongest on algebraic identities** (field arithmetic, ring algebra) and preamble-backed claims. Claims involving `Real.rpow` with variable exponents are brittle.
- **Frontier outcomes are uneven.** Recent formalizer-only runs now clear
  contraction-mapping and monotone-sequence cases, but strict-concavity /
  extreme-value formalization is still brittle.
- **General-equilibrium and richer game-theory claims** still tend to need definitions beyond the current preamble library.
- **Axiom info is best-effort.** Product UIs should treat missing `axiom_info` as "not available" rather than as a proof failure.
- **The Leanstral model is a labs endpoint** — not a permanent production API. Plan for prover backend swaps.
- **Each verification run takes 30-120 seconds.** Plan UX accordingly.
- **Railway Hobby plan.** Resource limits untested under concurrent load. Lean + Mathlib is memory-intensive.
- **Deploy latency.** Railway rebuilds can take 10+ minutes, so validate with
  local CI and Docker first, then treat Railway smoke checks as confirmation.
- **Runtime port split.** Railway runs the container on `PORT=8080`; local
  Docker examples may still expose host port `8000`. External clients should
  target the public base URL, not a hardcoded internal port.

## CORS

The API allows all origins (`*`). No authentication is currently required at the API level — auth should be implemented at the frontend layer.
