# LeanEcon API Guide

LeanEcon exposes a versioned REST API for claim classification, formalization,
proof generation, verification, explanation, cache inspection, and lightweight
run metrics.

Verify jobs are asynchronous and concurrency-safe: each run uses isolated
temporary Lean files for proving and final verification, so multiple jobs can
execute without clobbering a shared `Proof.lean`.

Base docs:

- OpenAPI schema: `/openapi.json`
- Interactive docs: `/docs`

## Recommended v1 workflow

1. `POST /api/v1/classify` *(optional — advisory only, not required before formalize)*
2. `POST /api/v1/formalize` *(with optional `preamble_names`)*
3. Optionally edit the returned `theorem_code`
4. `POST /api/v1/verify`
5. Track the job with either:
   - `GET /api/v1/jobs/{job_id}`
   - `GET /api/v1/jobs/{job_id}/stream`
6. Optionally call `POST /api/v1/explain`

> **Note:** Classification is no longer a required gate before formalization.
> The formalizer attempts all claims directly. Use `/classify` for frontend UX
> (showing scope hints, suggesting preamble modules) but not as a prerequisite.

## 1. Classify (optional)

Use `POST /api/v1/classify` to get advisory information about a claim's scope
and relevant preamble modules. This is useful for frontend UX but is **not**
required before calling `/formalize`.

Request:

```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma."
}
```

Important response fields:

- `cleaned_claim`: normalized claim text after lightweight cleaning
- `category`: `RAW_LEAN`, `ALGEBRAIC`, `MATHLIB_NATIVE`, `DEFINABLE`, or `REQUIRES_DEFINITIONS`
- `formalizable`: quick yes/no signal for whether to continue
- `reason`: rejection explanation for out-of-scope claims
- `definitions_needed`: supporting detail for `DEFINABLE` claims
- `preamble_matches`: reusable LeanEcon modules that may help formalization
- `suggested_reformulation`: optional reformulation hint
- `error_code`: machine-readable classifier outcome

Classifier note:

- the LLM-facing prompt still uses `ALGEBRAIC_OR_CALCULUS` and `REQUIRES_CUSTOM_THEORY`
- `classify_claim()` maps those to the API-facing categories `ALGEBRAIC` and `REQUIRES_DEFINITIONS`
- `MATHLIB_NATIVE` is an API-facing formalizable category for claims that likely need direct Mathlib imports rather than LeanEcon preamble modules

Interpretation:

- `RAW_LEAN`: skip directly to `POST /api/v1/verify`
- `ALGEBRAIC`: continue to `POST /api/v1/formalize`
- `MATHLIB_NATIVE`: continue to `POST /api/v1/formalize`; the formalizer will use an internal Mathlib navigation hint from classification
- `DEFINABLE`: continue to `POST /api/v1/formalize`, optionally using `preamble_matches`
- `REQUIRES_DEFINITIONS`: stop or ask for a reformulation

## 2. Formalize

Use `POST /api/v1/formalize` to turn natural language or LaTeX into a Lean
theorem file containing `:= by sorry`.

Request:

```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma.",
  "preamble_names": ["crra_utility"]
}
```

Important request fields:

- `raw_claim`: plain text, LaTeX, or raw Lean input
- `preamble_names`: optional explicit preamble module names to inject

Use [`PREAMBLE_CATALOG.md`](./PREAMBLE_CATALOG.md) to choose valid
`preamble_names`.

Important response fields:

- `success`: whether the theorem compiled with `sorry`
- `theorem_code`: full Lean file content to review or edit
- `attempts`: number of formalization or repair attempts used
- `formalization_failed`: whether the claim was rejected as out of scope
- `failure_reason`: explanation for a formalization rejection
- `preamble_used`: names of injected preamble definitions
- `diagnosis`, `suggested_fix`, `fixable`: repair guidance when formalization fails
- `error_code`: machine-readable formalization outcome

If `raw_claim` already looks like Lean and contains a proof stub, this endpoint
passes it through unchanged with `attempts = 0`.

## 3. Verify

Use `POST /api/v1/verify` to queue proof generation plus final Lean
verification.

Request:

```json
{
  "theorem_code": "import Mathlib\nopen Real\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  sorry",
  "explain": false
}
```

Important request rules:

- `theorem_code` must look like a Lean theorem, lemma, or example
- it must still contain `:= by sorry`
- `explain=true` asks LeanEcon to include an explanation in the final job result
- the endpoint responds immediately with HTTP `202`

Verification notes:

- the proving job edits a per-run working file such as `AgenticProof_<id>.lean`
- final Lean acceptance is checked by compiling an isolated per-run temp file
  with `lake env lean`
- concurrent verify jobs are supported because the API no longer routes all
  verification through a shared `LeanEcon/Proof.lean`

Queue response:

```json
{
  "job_id": "8edb1a2b-3cf3-4b59-9a0a-9f4b4655c9d6",
  "status": "queued"
}
```

### Polling jobs

Use `GET /api/v1/jobs/{job_id}` to read job status and final output. Poll until
`status` becomes `completed` or `failed`.

Response fields:

- `job_id`: the same identifier returned by verify
- `status`: `queued`, `running`, `completed`, or `failed`
- `result`: final verify payload when completed
- `error`: exception text when failed
- `queued_at`: UTC timestamp when the job was accepted
- `started_at`: UTC timestamp when the background worker started it
- `finished_at`: UTC timestamp when the job completed or failed
- `last_progress_at`: UTC timestamp of the latest progress event observed
- `current_stage`: most recent pipeline stage reported for the job

Important fields inside `result`:

- `success`: whether Lean accepted the final proof
- `phase`: `verified`, `proved`, or `failed`
- `lean_code`: final Lean file produced by the proving run
- `proof_strategy`: high-level proof plan
- `proof_tactics`: tactic script or tactics summary
- `errors` / `warnings`: Lean diagnostics
- `elapsed_seconds`: total pipeline runtime
- `from_cache`: whether the response came from the verified-result cache
- `partial`: whether the prover timed out and returned partial output
- `stop_reason`: prover stop reason when reported
- `tool_trace`: ordered deep-trace events from the proving run
- `tactic_calls`: tactic-application attempts with triggering Lean errors when available
- `trace_schema_version`: schema marker for `tool_trace` / `tactic_calls`
- `axiom_info`: optional axiom-usage metadata from final verification
- `explanation`: optional natural-language explanation when `explain=true`
- `explanation_generated`: whether the explanation was model-generated
- `error_code`: machine-readable verification outcome

`axiom_info` is best-effort. Cache hits, local fast-path successes, or timed-out
MCP axiom checks may leave it as `null` even when verification succeeds. When
present, its shape is:

```json
{
  "axioms": ["propext", "Classical.choice"],
  "sound": true,
  "has_sorry_ax": false,
  "nonstandard_axioms": []
}
```

Phase meanings:

- `verified`: Lean accepted the proof
- `proved`: a proof was generated, but Lean rejected it
- `failed`: the pipeline did not reach a valid proof

Observability notes:

- `tool_trace` keeps the existing field name for backward compatibility, but new
  runs include ordered tool-call records with tool kind, arguments, normalized
  result text, status, and parsed diagnostic payloads for
  `lean_diagnostic_messages`
- `tactic_calls` now record retry-triggering Lean kernel errors and whether the
  following diagnostic check succeeded
- the job envelope now includes additive timestamps plus `current_stage`, which
  makes a long-lived `running` job debuggable without changing the existing
  verify payload shape
- the JSONL run log lives at `logs/runs.jsonl` by default, or at
  `${LEANECON_STATE_DIR}/logs/runs.jsonl` when `LEANECON_STATE_DIR` is set

## SSE job streaming

`GET /api/v1/jobs/{job_id}/stream` returns a Server-Sent Events stream with
`Content-Type: text/event-stream`.

Each event is a single JSON object on a `data:` line:

```text
data: {"type":"progress","stage":"formalize","message":"Calling Leanstral...","status":"running"}

data: {"type":"progress","stage":"agentic_run","message":"Leanstral proving loop started...","status":"running"}

data: {"type":"complete","status":"completed"}
```

Event fields:

- `type`: `progress` or `complete`
- `stage`: pipeline stage name for progress events
- `message`: human-readable progress text for progress events
- `status`: stage or job status such as `running`, `done`, `error`, `completed`, `failed`
- `error`: present on failed `complete` events

Notes:

- completed jobs return a single `complete` event and then close
- failed jobs return `{"type":"complete","status":"failed","error":"..."}` and then close
- keepalive comments may appear as `: keepalive`
- typical progress stages include `parse`, `formalize`, `prover_dispatch`,
  `agentic_init`, `agentic_setup`, `agentic_run`, `agentic_check`,
  `agentic_verify`, `cache`, and `explain`
- the stream does not include the final verify payload; fetch `GET /api/v1/jobs/{job_id}` for that

Frontend example:

```javascript
const eventSource = new EventSource(`/api/v1/jobs/${jobId}/stream`);

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === "progress") {
    updateProgressUI(data.stage, data.message, data.status);
    return;
  }

  if (data.type === "complete") {
    eventSource.close();
    fetchJobResult(jobId);
  }
};
```

## Explain

Use `POST /api/v1/explain` to get a natural-language explanation of a pipeline
outcome. This endpoint is useful when you already have intermediate artifacts
and do not want to rerun verification.

Request:

```json
{
  "original_claim": "1 + 1 = 2",
  "verification_result": {
    "success": true,
    "proof_generated": true,
    "formalization_failed": false
  }
}
```

Supported inputs:

- `original_claim`: required
- `theorem_code`: optional formalized theorem
- `verification_result`: optional final verify result
- `formalization_result`: optional formalization output
- `classification_result`: optional classification output

Response:

```json
{
  "explanation": "The proof is valid.",
  "generated": false,
  "error_code": "none"
}
```

## Metrics

`GET /api/v1/metrics` aggregates metrics from the append-only evaluation log at
`logs/runs.jsonl` by default, or `${LEANECON_STATE_DIR}/logs/runs.jsonl` when
`LEANECON_STATE_DIR` is configured.

Example response:

```json
{
  "total_runs": 12,
  "verified": 9,
  "formalization_failures": 1,
  "proof_failures": 2,
  "cache_hits": 3,
  "partial_runs": 1,
  "avg_elapsed_seconds": 18.4,
  "verification_rate": 0.75,
  "cache_hit_rate": 0.25
}
```

This endpoint is meant for lightweight development-time visibility, not a full
metrics stack.

For release gating, prefer local lint, non-live pytest, Lean/MCP smoke checks,
and local Docker validation before trusting any Railway response.

## Offline evaluation scripts

LeanEcon also includes script-level evaluation tooling that operates on the
append-only log and pipeline outputs.

### Deep trace analysis

```bash
./leanEconAPI_venv/bin/python scripts/analyze_traces.py --runs-file logs/runs.jsonl --format both
```

This script computes:

- Tool Call Efficiency: successful tactic applications divided by total tool calls
- Tactic Depth: average number of distinct tactic heads in successful proofs
- Error Frequency: most common Lean kernel errors seen in failed proof attempts

### Semantic grading

```bash
./leanEconAPI_venv/bin/python scripts/semantic_grader.py \
  --claim "Under CRRA utility, relative risk aversion is constant." \
  --theorem-file docs/legacy_examples/crra_pass.lean
```

This script uses Leanstral as a mathematical referee and returns structured
JSON with `score`, `verdict`, `rationale`, and `trivialization_flags`.

### Uncharted evaluations

```bash
./leanEconAPI_venv/bin/python scripts/run_uncharted_evals.py \
  tests/fixtures/claims/test_claims.jsonl \
  --profile ci
```

Input JSONL records should include:

- `id`: stable case identifier
- `raw_claim`: natural-language claim
- optional `expect`: `verify`, `formalize`, or `fail_gracefully`
- optional `eval_stage`: `formalization`, `prove`, or `e2e`
- optional `theorem_code` / `preformalized_theorem` for prover-only cases
- optional `preamble_names`, `tags`, and `notes`

The runner is stage-aware:

- `expect: verify` runs formalization plus proving
- `expect: formalize` and `expect: fail_gracefully` stop after formalization
- `theorem_code` / `preformalized_theorem` runs prover-only evaluation
- unlabeled raw-claim cases still default to full end-to-end evaluation

It writes `case_records.jsonl`, `results.json`, and `report.md` under
`outputs/uncharted_evals/`.

This harness is currently a frontier-diagnostics tool, not the main release or
CI benchmark. A partial rerun on March 22, 2026 across 7 frontier attempts on 2
hard claims produced a `0.978` tool-call waste ratio, repeated Lean LSP startup
timeouts, and one Mistral `3051` input-too-large failure. Use explicit profiles:

- `--profile ci` for cheap day-to-day regression tracking
- `--profile core` when you also want semantic grading
- `--profile frontier` for expensive research probes on hard claims

The summary metrics are now stage-aware too:

- `Formalization Robustness` only counts cases that actually ran formalization
- `Agentic Proving Power` only counts proof-stage cases
- `Expectation Benchmark Score` reports how often labeled benchmark targets were met

## Cache endpoints

Use these operational endpoints to inspect or clear the verified-result cache:

- `GET /api/v1/cache/stats` returns:

```json
{
  "size": 4
}
```

- `DELETE /api/v1/cache` returns:

```json
{
  "status": "cleared"
}
```

The verified-result cache lives at `data/verified_cache.json` by default, or at
`${LEANECON_STATE_DIR}/data/verified_cache.json` when `LEANECON_STATE_DIR` is
set.

## Validation Workflow

Use local checks as the release gate before considering a Railway rebuild:

- `ruff check src/ tests/ scripts/`
- `pytest -m "not live and not slow"`
- local Lean/MCP smoke checks such as `./leanEconAPI_venv/bin/python src/mcp_smoke_test.py`
- `docker build .`
- local container `curl` checks against `/health`, `/api/v1/metrics`, and `/api/v1/cache/stats`

Railway `curl` checks are useful only after a deliberate deploy, because the
currently deployed instance may still be serving an older build.

## Health

`GET /health` returns:

```json
{
  "status": "ok"
}
```

## Error handling

- `422` means the request payload was blank or structurally invalid
- `404` means a job was not found or expired
- `500` means an unexpected internal failure occurred in classification,
  formalization, verification, explanation, or metrics aggregation
