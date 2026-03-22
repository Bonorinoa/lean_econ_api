---
name: leanecon-api
description: "Integration guide for the LeanEcon formal verification API. Use whenever building frontends, dashboards, eval harnesses, or services connecting to LeanEcon for mathematical claim verification. Triggers on: UI for theorem verification, SSE streaming, async job polling, classify/formalize/verify workflows, test suites, formalization debugging, observability logs, or dashboards combining LeanEcon endpoints. Also trigger on mentions of LeanEcon, preamble library, EconLib, verification dashboard, evaluation harness, or 'test the API' / 'build a dashboard' in this project context."
---

# LeanEcon API Integration Skill

LeanEcon is a headless formal verification microservice that takes mathematical claims (natural language, LaTeX, or raw Lean 4) and produces machine-checked proofs using Lean 4 and Mathlib.

**Base URL:** `https://leaneconapi-production.up.railway.app`
**Interactive docs:** `{BASE_URL}/docs` (Swagger UI)
**OpenAPI schema:** `{BASE_URL}/openapi.json`
**Source of truth:** [`src/api.py`](../../src/api.py), [`docs/API.md`](../API.md), and the live `/openapi.json`.

## Architecture overview

LeanEcon has a three-layer trust model that frontends should communicate to users:

1. **Stochastic layer** — Leanstral (LLM) generates candidate formalizations and proofs. May fail. Output quality varies.
2. **Human-in-the-loop** — The user reviews the formalized theorem before proving. This is where frontends add value.
3. **Deterministic layer** — Lean 4's kernel verifies the proof from axioms. If it passes, it's mathematically certified. Not LLM confidence — formal certainty.

## Core workflow (6 steps)

Every frontend should implement this sequence:

```
1. POST /api/v1/classify    → (OPTIONAL) Advisory scope check + preamble suggestions
2. POST /api/v1/formalize   → Get a Lean theorem stub (with sorry). Pass preamble_names if needed.
3. [User reviews/edits]     → Frontend presents theorem for review
4. POST /api/v1/verify      → Returns 202 + job_id (async)
5. GET /api/v1/jobs/{id}/stream  → SSE progress events
   GET /api/v1/jobs/{id}         → Final result when complete
6. POST /api/v1/explain     → Natural language explanation (optional)
```

> **Important:** Classification is no longer an internal gate for formalization.
> The formalizer attempts all claims directly. Use `/classify` for frontend UX
> (scope hints, preamble suggestions) but you can skip it and go straight to
> `/formalize`. Preamble injection is opt-in via explicit `preamble_names`.
>
> **Also important:** `/verify` is queue-based and concurrency-safe. LeanEcon no
> longer routes verification through a shared `LeanEcon/Proof.lean`; proving and
> final verification use isolated per-run temp files. The job-status response
> now also includes additive observability metadata such as queue/start/finish
> timestamps and the latest reported pipeline stage.

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

The formalizer retries up to 3 times with diagnostic feedback between attempts.
`formalization_failed=true` is reserved for explicit out-of-scope rejections; a
compile failure after retries can still return `formalization_failed=false`
alongside `diagnosis`, `suggested_fix`, and `fixable`.

### POST /api/v1/verify

Submits a theorem for agentic proving. **This is async — returns immediately with a job ID.**

**Request:**
```json
{
  "theorem_code": "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by sorry",
  "explain": false
}
```

`/api/v1/verify` currently accepts only:
- `theorem_code`
- `explain`

`pass_k` is part of the offline eval harness, not the public verify endpoint.

**Response (HTTP 202):**
```json
{
  "job_id": "abc123-def456",
  "status": "queued"
}
```

The proof takes 30-120 seconds. You MUST either poll or stream — never block the UI.

### GET /api/v1/jobs/{job_id}/stream

SSE stream of progress events. Preferred over polling.

```javascript
const eventSource = new EventSource(`${BASE_URL}/api/v1/jobs/${jobId}/stream`);

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === "progress") {
    // Typical stages: "formalize", "agentic_init", "agentic_setup",
    // "agentic_run", "agentic_verify", "explain"
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
  "status": "completed",
  "queued_at": "2026-03-22T19:00:00+00:00",
  "started_at": "2026-03-22T19:00:01+00:00",
  "finished_at": "2026-03-22T19:00:35+00:00",
  "last_progress_at": "2026-03-22T19:00:32+00:00",
  "current_stage": "agentic_verify",
  "result": {
    "success": true,
    "phase": "verified",
    "lean_code": "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by norm_num",
    "errors": [],
    "warnings": [],
    "proof_strategy": "Use norm_num.",
    "proof_tactics": "norm_num",
    "theorem_statement": "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by sorry",
    "formalization_attempts": 0,
    "formalization_failed": false,
    "failure_reason": null,
    "output_lean": "/app/outputs/Proof_20260322_062903.lean",
    "proof_generated": true,
    "elapsed_seconds": 34.95,
    "from_cache": false,
    "partial": false,
    "stop_reason": "proof_complete",
    "axiom_info": null,
    "error_code": "none",
    "explanation": null,
    "explanation_generated": null
  },
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
- `GET /api/v1/metrics` → Aggregate verification stats from the JSONL eval log
- `GET /api/v1/cache/stats` → `{"size": N}`
- `DELETE /api/v1/cache` → Clear verified result cache

Runtime state lives in repo-local paths by default. When `LEANECON_STATE_DIR`
is set, the JSONL run log moves to `${LEANECON_STATE_DIR}/logs/runs.jsonl` and
the verified-result cache moves to `${LEANECON_STATE_DIR}/data/verified_cache.json`.

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
- `proof_timeout` — Prover timed out (check `partial` field)
- `verification_rejected` — Lean rejected the proof
- `verification_sorry` — Proof contains sorry
- `internal_error` — Unexpected server-side failure

## Observability and data flywheel

### runs.jsonl — the evaluation log

Every verification run appends a structured JSON line to `logs/runs.jsonl` by
default, or to `${LEANECON_STATE_DIR}/logs/runs.jsonl` when `LEANECON_STATE_DIR`
is set. This is the source of truth for metrics and offline evaluation. Each
entry includes: claim text, classification result, formalization result,
verification result, tool call counts, timing, errors, and axiom info.

The `/api/v1/metrics` endpoint aggregates this log into summary statistics. For deeper analysis, process `runs.jsonl` directly.

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
5. **Re-run and compare** — track metrics across iterations

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
default CI benchmark. A partial rerun on March 22, 2026 across 7 frontier
attempts on 2 hard claims produced a `0.978` tool-call waste ratio, repeated
Lean LSP startup timeouts, and one Mistral `3051` input-too-large failure.

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

### Designing test claims

Test claims should span these categories:

**Tier 1 — Should pass (baseline regression):**
Algebraic identities and preamble-backed claims where the system has proven track record.
- "Under CRRA utility, relative risk aversion equals gamma"
- "Cobb-Douglas output elasticity w.r.t. capital equals alpha"
- "1 + 1 = 2"
- Budget constraint equalities

**Tier 2 — Should formalize, may not prove (stretch goals):**
Claims that require deeper Mathlib engagement but are within formalization scope.
- Derivative-based claims using preamble lemmas
- CES production properties
- Envelope theorem applications
- Many claims that classify as `MATHLIB_NATIVE`

**Tier 3 — Uncharted territory (capability probes):**
Claims that test the system's limits. Expect formalization failures here — the diagnostic data is the value.
- Fixed-point theorems (Banach, Brouwer)
- Bellman operator properties
- Measure-theoretic claims
- Hessian/second-order conditions

**Tier 4 — Should be correctly rejected:**
Claims the classifier should route to `REQUIRES_DEFINITIONS`.
- "Nash equilibrium exists in finite games"
- General equilibrium existence
- Claims requiring definitions not in Mathlib or the preamble

### Known failure patterns from evaluation

The failure picture is now split across layers. Earlier March 2026 runs exposed
formalization problems first; the March 22, 2026 partial frontier rerun showed
that on hard preformalized claims the prover loop and MCP reliability can become
the dominant bottlenecks. Do not assume "formalization is always the problem."

1. **Hallucinated Mathlib paths and theorem names.** The formalizer or prover guesses identifiers such as `StrictConcaveOn.neg_deriv2` or `StrictConcaveOn.contDiff_iff_deriv2_nonpos` that do not exist. Fix: verify identifiers with search before committing to them, and add search-assisted import/name discovery during formalization.

2. **MCP startup and workspace reliability on frontier claims.** The March 22, 2026 rerun surfaced repeated Lean LSP startup timeouts and occasional file/workspace path failures. Distinguish these from mathematical proving failures in dashboards and reports.

3. **Type class and calculus API mismatches.** Claims about derivatives, Hessians, normed spaces, or product spaces still trigger `failed to synthesize instance`, `Unknown constant`, or function-shape mismatches. The model often reaches for one-dimensional `deriv` lemmas on higher-dimensional `fderiv` goals.

4. **Context blow-up on long hard attempts.** One March 22, 2026 frontier attempt failed with Mistral error `3051` (`Input too large: couldn't fit with truncation`). Large `tool_trace` and retry histories must be capped aggressively.

5. **Guardrails help, but do not solve frontier math.** Duplicate read-only query blocking, search budgets, and total tool budgets now stop some high-waste loops early. That saves cost, but it also means frontier eval failures often end as honest "stopped before burning more budget" results rather than full theorem attempts.

6. **Use staged evals for honest routine measurement.** For regular progress tracking, prefer:
   - formalization-only evals
   - prover-only evals on preformalized theorem stubs
   - MCP smoke tests
   - small end-to-end `pass@1` regressions
   Keep `uncharted` pass@k runs for explicit capability probes.

## UX best practices

### What to show during the 30-120s verification wait

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
3. **Raw Lean 4** — Full `.lean` file content with `import Mathlib` and `:= by sorry`

Raw Lean input is detected automatically by classify (returns `RAW_LEAN`) and bypasses formalization.

### The review step matters

After formalize returns `theorem_code`, ALWAYS show it to the user before calling verify. This is the human-in-the-loop layer. The user should confirm "yes, that's what I meant" before spending 30-120s on proving.

### Partial results and timeouts

If `partial: true` in the result, the prover timed out but returned its best effort. Show the partial proof with a "Timed out — retry?" option. The `stop_reason` field explains why.

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
classify → formalize → [review] → verify → explain
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

- **Formalization is the bottleneck.** ~80% of advanced claims fail at formalization, not proving. The formalizer doesn't know all Mathlib paths for topology, measure theory, or advanced analysis.
- **Verification is stochastic.** The same claim may pass on one run and fail on the next. Offer retry buttons.
- **Currently strongest on algebraic identities** (field arithmetic, ring algebra) and preamble-backed claims. Claims involving `Real.rpow` with variable exponents are brittle.
- **Fixed-point and measure-theoretic claims** are stretch goals, not impossible in principle. Expect many of them to land in `MATHLIB_NATIVE` or fail during formalization.
- **General-equilibrium and richer game-theory claims** still tend to need definitions beyond the current preamble library.
- **Axiom info is best-effort.** Product UIs should treat missing `axiom_info` as "not available" rather than as a proof failure.
- **The Leanstral model is a labs endpoint** — not a permanent production API. Plan for prover backend swaps.
- **Each verification run takes 30-120 seconds.** Plan UX accordingly.
- **Railway Hobby plan.** Resource limits untested under concurrent load. Lean + Mathlib is memory-intensive.
- **Deploy latency.** Railway rebuilds can take 10+ minutes, so validate with
  local CI and Docker first, then treat Railway smoke checks as confirmation.

## CORS

The API allows all origins (`*`). No authentication is currently required at the API level — auth should be implemented at the frontend layer.
