# LeanEcon API Guide

LeanEcon exposes a versioned REST API for claim classification, formalization,
direct Lean compilation, proof generation, final verification, explanation,
cache inspection, and benchmark snapshots.

Some endpoints now include optional provider telemetry and conservative cost
estimates when real usage data exists. These fields are for observability, not
billing, do not imply stable provider pricing or a stably free Leanstral tier,
and `/api/v1/lean_compile` remains local-only.

This guide is the operational source of truth. For the architecture and trust
model, see [`docs/leanstral_architecture.html`](./leanstral_architecture.html).
For the project landing page, see [`README.md`](../README.md).

OpenAPI schema: `/openapi.json`

Interactive docs: `/docs`

## Recommended Workflow

1. `POST /api/v1/classify` if you want scope hints or preamble suggestions.
2. `POST /api/v1/formalize` to turn the claim into a Lean theorem stub.
3. Review or edit the theorem text.
4. `POST /api/v1/verify` to queue proof generation and final Lean checking.
5. Poll `GET /api/v1/jobs/{job_id}` or stream `GET /api/v1/jobs/{job_id}/stream`.
6. Call `POST /api/v1/explain` after the job finishes if you want a summary.

If you already have Lean theorem code with `:= by sorry`, skip formalization
and go straight to `/api/v1/verify`.

If you already have complete Lean code and want a direct compiler check, use
`POST /api/v1/lean_compile`. It is an optional compile/debug primitive, not the
default workflow.

In product terms:

- `/api/v1/formalize` is the claim-shaping step
- `/api/v1/lean_compile` is the thin synchronous compile/debug primitive
- `/api/v1/verify` is the async agentic proving path

## Compatibility Notes

- Legacy unversioned routes `/api/classify`, `/api/formalize`, and
  `/api/verify` remain as deprecated wrappers for backward compatibility.
- `/health` stays unversioned.
- The exhaustive request/response schema is always the live OpenAPI document.

## Endpoint Summary

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/classify` | Advisory claim classification and preamble hints |
| `POST` | `/api/v1/formalize` | Claim-to-theorem shaping with `:= by sorry` |
| `POST` | `/api/v1/lean_compile` | Direct Lean compilation without the prover |
| `POST` | `/api/v1/verify` | Async proof generation plus final Lean verification |
| `GET` | `/api/v1/jobs/{job_id}` | Poll async verify job status and final result |
| `GET` | `/api/v1/jobs/{job_id}/stream` | Stream verify progress as SSE |
| `POST` | `/api/v1/explain` | Natural-language explanation of a pipeline outcome |
| `GET` | `/api/v1/metrics` | Aggregate metrics from the JSONL run log |
| `GET` | `/api/v1/benchmarks/latest` | Summary-only view of the newest benchmark snapshot |
| `GET` | `/api/v1/cache/stats` | Inspect verified-result cache size |
| `DELETE` | `/api/v1/cache` | Clear the verified-result cache |
| `GET` | `/health` | Liveness check |

## POST /api/v1/classify

Use this endpoint for optional scope hints. It is advisory only and is not a
prerequisite for formalization.

Request:

```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma."
}
```

Important response fields:

- `cleaned_claim`: normalized claim text after lightweight cleaning
- `category`: one of `RAW_LEAN`, `ALGEBRAIC`, `MATHLIB_NATIVE`, `DEFINABLE`,
  or `REQUIRES_DEFINITIONS`
- `formalizable`: whether the claim should continue to formalization
- `reason`: rejection explanation when the claim needs missing definitions
- `is_raw_lean`: whether the input already looked like Lean code
- `error_code`: machine-readable classifier outcome
- `definitions_needed`: supporting detail for `DEFINABLE` claims
- `preamble_matches`: reusable LeanEcon preamble modules
- `auto_preamble_matches`: the bounded preamble set the backend would
  auto-select if you do not choose explicit preambles at formalize time
- `suggested_reformulation`: optional rewrite hint

Behavior notes:

- raw Lean input returns `RAW_LEAN` immediately
- `REQUIRES_DEFINITIONS` is the only category that should stop the workflow
- `ALGEBRAIC`, `MATHLIB_NATIVE`, and `DEFINABLE` are all formalizable
- `provider_telemetry`, when present, is observability metadata for the
  classifier call rather than a pricing commitment

Interpretation:

| Category | Recommended next step |
| --- | --- |
| `RAW_LEAN` | Skip formalize and go straight to `verify` if the theorem still contains `:= by sorry` |
| `ALGEBRAIC` | Continue to `formalize` |
| `MATHLIB_NATIVE` | Continue to `formalize`; expect direct Mathlib imports rather than LeanEcon preambles |
| `DEFINABLE` | Continue to `formalize`, optionally using `preamble_matches` |
| `REQUIRES_DEFINITIONS` | Stop or ask for a reformulation |

## POST /api/v1/formalize

Use this endpoint to turn natural language or LaTeX into a Lean theorem file
containing `:= by sorry`.

Request:

```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma.",
  "preamble_names": ["crra_utility"]
}
```

Important request fields:

- `raw_claim`: plain text, LaTeX, or raw Lean 4 input
- `preamble_names`: optional explicit preamble module names

Preamble policy:

- explicit `preamble_names` are authoritative and exact
- unknown preamble names now return HTTP `422` instead of being silently dropped
- when `preamble_names` is empty, the formalizer may still add bounded auto-selected
  preambles using retrieval and curated hints

Integration note:

- clients handing off preamble-backed theorem-library examples into
  `/api/v1/formalize` should forward the matching `preamble_names`; sending
  only the natural-language claim can silently drop useful context and reduce
  formalization reliability

Important response fields:

- `success`: whether the theorem compiled with `sorry`
- `theorem_code`: full Lean file content returned by the formalizer
- `attempts`: number of formalization or repair attempts used
- `errors`: Lean errors from the last failed formalization attempt
- `formalization_failed`: whether the claim was rejected as out of scope
- `failure_reason`: model-provided reason for rejection
- `error_code`: machine-readable formalization outcome
- `preamble_used`: names of injected preamble definitions
- `diagnosis`: failure analysis when repair attempts are exhausted
- `suggested_fix`: concrete suggestion for fixing the formalization
- `fixable`: whether a human edit is likely to help
- `formalization_context`: structured handoff metadata for downstream `/verify`
  calls, including selected preambles, candidate imports, identifiers, runtime
  search directives, retrieval notes, MCP hits, and validation metadata

Behavior notes:

- if the input already looks like Lean and contains a proof stub, the endpoint
  passes it through unchanged with `attempts = 0`
- if `preamble_names` is empty, the formalizer may auto-select matching
  preambles using bounded retrieval
- compile failures are bucketed into import/module, identifier, typeclass,
  syntax, or semantic classes before targeted repair
- the runtime formalize path now enables bounded MCP retrieval by default and
  folds the results into `formalization_context.runtime_search_plan`
- MCP-backed search stays health-gated; when unavailable, the formalizer falls
  back to curated hints plus local Lean compilation
- `provider_telemetry`, when present, is observability metadata for the
  formalizer call set rather than a public pricing commitment

## POST /api/v1/lean_compile

Use this endpoint to compile a complete Lean file directly with the local Lean
toolchain. It bypasses both formalization and the agentic prover.

Request:

```json
{
  "lean_code": "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  norm_num\n",
  "filename": "one_plus_one.lean",
  "check_axioms": false
}
```

Important request fields:

- `lean_code`: complete Lean file content to compile as-is
- `filename`: optional label used to derive the temporary Lean filename
- `check_axioms`: optional best-effort axiom check after a successful compile

Important response fields:

- `success`: whether Lean accepted the file
- `errors` / `warnings`: compiler diagnostics
- `stdout` / `stderr`: captured compiler output
- `verification_method`: compiler path used for the check
- `elapsed_ms`: wall-clock compile time in milliseconds
- `axiom_info`: optional axiom usage payload when `check_axioms=true`
- `telemetry`: optional local-only usage telemetry with `estimated_cost_*`
  left null because direct compile work is not LLM spend

Behavior notes:

- this endpoint does not queue a job
- this endpoint does not invoke the prover
- it is useful for kernel-truth checks and debugging pre-written Lean code
- it is tagged as local-only telemetry and excluded from LLM cost totals
- a file that still contains `sorry` will fail this endpoint

## POST /api/v1/verify

Use this endpoint to queue proof generation plus final Lean verification.
It returns HTTP `202` immediately.

Request:

```json
{
  "theorem_code": "import Mathlib\nopen Real\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  sorry",
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

Important request rules:

- `theorem_code` must look like a Lean theorem, lemma, or example
- it must still contain `:= by sorry`
- `explain=true` asks LeanEcon to include an explanation in the final job result
- for the fastest user-facing flow, keep `explain=false` and call
  `/api/v1/explain` after the job completes
- `formalization_context` is optional but recommended when `/formalize` and
  `/verify` are decoupled across client steps
- when `formalization_context` is present, preserve it unchanged so the prover
  receives the formalizer's runtime search plan and retrieval hits
- explicit `preamble_names`, when provided to `verify`, are authoritative and
  must exactly match `formalization_context.selected_preambles` if both are sent
- `reasoning_preset` may be `normal`, `medium`, or `high`
- `budget_overrides` exposes experimental low-level controls such as wall-clock,
  per-request timeout, append-round, and tool-budget caps

Queue response:

```json
{
  "job_id": "8edb1a2b-3cf3-4b59-9a0a-9f4b4655c9d6",
  "status": "queued"
}
```

Behavior notes:

- the proving job edits a per-run working file such as `AgenticProof_<id>.lean`
- final Lean acceptance is checked by compiling an isolated per-run temp file
  with `lake env lean`
- concurrent verify jobs are supported because the API no longer routes all
  verification through a shared `LeanEcon/Proof.lean`

## GET /api/v1/jobs/{job_id}

Use this endpoint to poll the status of a queued or completed verify job.
Poll until `status` becomes `completed` or `failed`.

Important response fields:

- `job_id`: the same identifier returned by verify
- `status`: `queued`, `running`, `completed`, or `failed`
- `result`: final verify payload when completed
- `error`: exception text when failed
- `queued_at`: UTC timestamp when the job was accepted
- `started_at`: UTC timestamp when the background worker started it
- `finished_at`: UTC timestamp when the job completed or failed
- `last_progress_at`: UTC timestamp of the latest progress event observed
- `current_stage`: the most recent pipeline stage reported for the job
- `stage_timings`: per-stage elapsed milliseconds keyed by stage name

Important fields inside `result`:

- `success`: whether Lean accepted the final proof
- `phase`: `verified`, `proved`, or `failed`
- `lean_code`: final Lean file produced by the proving run
- `proof_strategy`: high-level proof plan
- `proof_tactics`: tactic script or tactic summary
- `theorem_statement`: theorem text that entered the proving stage
- `formalization_attempts`: number of formalization attempts before proving
- `formalization_failed`: whether the pipeline failed during formalization
- `failure_reason`: reason for an early formalization failure, when present
- `output_lean`: optional output artifact path
- `proof_generated`: whether the prover produced a proof attempt
- `elapsed_seconds`: total pipeline runtime
- `from_cache`: whether the result came from the verified-result cache
- `partial`: whether the prover timed out and returned partial output
- `stop_reason`: prover stop reason when reported
- `tool_trace`: ordered deep-trace events from the proving run
- `tactic_calls`: tactic attempts with triggering Lean errors when available
- `trace_schema_version`: schema marker for `tool_trace` and `tactic_calls`
- `axiom_info`: optional axiom-usage metadata from final verification
- `explanation`: optional natural-language explanation when `explain=true`
- `explanation_generated`: whether the explanation was model-generated
- `error_code`: machine-readable verification outcome
- `provider_telemetry`: aggregate observability metadata for formalization and
  proving calls when usage payloads were available
- `explanation_telemetry`: separate observability metadata for the optional
  explanation call
- `formalization_context`: the structured formalizer handoff metadata actually
  used for the verify run, including retrieval hints and runtime search plan
- `budget`: resolved proving-budget settings plus compact usage telemetry such as
  append rounds used, tool calls used, stop reason, and timeout scope

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

## GET /api/v1/jobs/{job_id}/stream

Use this endpoint to stream verify job progress as Server-Sent Events.
The stream closes automatically after the job completes or fails.

Each event is a single JSON object on a `data:` line:

```text
data: {"type":"progress","stage":"formalize","message":"Calling Leanstral to formalize claim...","status":"running"}

data: {"type":"progress","stage":"agentic_run","message":"Leanstral proving loop started...","status":"running"}

data: {"type":"complete","status":"completed"}
```

Event fields:

- `type`: `progress` or `complete`
- `stage`: pipeline stage name for progress events
- `message`: human-readable progress text for progress events
- `status`: stage or job status such as `running`, `done`, `error`,
  `completed`, or `failed`
- `error`: present on failed `complete` events

Notes:

- completed jobs return a single `complete` event and then close
- failed jobs return `{"type":"complete","status":"failed","error":"..."}` and then close
- keepalive comments may appear as `: keepalive`
- the stream does not include the final verify payload; fetch
  `GET /api/v1/jobs/{job_id}` for that

## POST /api/v1/explain

Use this endpoint to get a natural-language explanation of a pipeline result.
It is useful when you already have intermediate artifacts and do not want to
rerun verification.

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

## GET /api/v1/metrics

Use this endpoint to aggregate metrics from the append-only evaluation log.
The default location is `logs/runs.jsonl`, or
`${LEANECON_STATE_DIR}/logs/runs.jsonl` when `LEANECON_STATE_DIR` is set.

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
metrics stack. If the log file is missing or empty, it returns a zeroed payload.

## GET /api/v1/benchmarks/latest

Use this endpoint to read the newest offline benchmark snapshot summary.
The API first checks `${LEANECON_STATE_DIR}/benchmarks/snapshots/` when a state
directory is configured, then falls back to the bundled
`benchmarks/snapshots/` directory.

If no snapshot exists yet, the endpoint can legitimately return `404` with:

```json
{"detail":"No benchmark snapshot found."}
```

The response is summary-only. It intentionally excludes per-claim internals.
Use the on-disk snapshot and report artifacts for benchmark debugging.

## GET /api/v1/cache/stats

Use this endpoint to inspect the verified-result cache.

Example response:

```json
{
  "size": 4
}
```

The verified-result cache lives at `data/verified_cache.json` by default, or at
`${LEANECON_STATE_DIR}/data/verified_cache.json` when `LEANECON_STATE_DIR` is
set.

## DELETE /api/v1/cache

Use this endpoint to clear the verified-result cache.

Example response:

```json
{
  "status": "cleared"
}
```

## GET /health

Use this endpoint for liveness checks.

Example response:

```json
{
  "status": "ok"
}
```

## Current Measured Status

As of the 2026-03-25 local release sweep:

- `./leanEconAPI_venv/bin/ruff check src tests scripts`: passed
- `./leanEconAPI_venv/bin/python -m pytest -m "not live and not slow" --tb=short -q`:
  `216 passed, 13 deselected`
- `./leanEconAPI_venv/bin/python scripts/production_smoke.py --base-url https://leaneconapi-production.up.railway.app --poll-interval 1 --max-polls 10`:
  exited `0` on 2026-03-25 after the tightened gate passed; `/health`,
  `/openapi.json`, `/api/v1/metrics`, `/api/v1/cache/stats`, classify, and
  formalize all returned success, and the sample verify job completed on the
  first poll from cache with `current_stage = "cache"` and `partial = false`
- latest completed full tier-1 lane report:
  [`benchmarks/reports/tier1_core_selected_full_full_20260325T151134Z.md`](../benchmarks/reports/tier1_core_selected_full_full_20260325T151134Z.md)
  shows:
  - `raw_claim -> full API`: `pass@1 = 0.333`
  - `theorem_stub -> verify`: `pass@1 = 1.000`
  - `raw_lean -> verify`: `pass@1 = 1.000`
- latest completed tier-1 formalizer-only report:
  [`benchmarks/reports/tier1_core_formalizer_only_20260325T181104Z.md`](../benchmarks/reports/tier1_core_formalizer_only_20260325T181104Z.md)
  shows:
  - `raw_claim -> formalizer-only gate`: `pass@1 = 0.833`
  - semantic `>=4` rate: `1.000`

The practical takeaway is unchanged: raw Lean and theorem-stub verification are
the strongest lanes; raw-claim full-API evaluation is still the weakest lane,
and the refreshed bounded formalizer-only gate is still volatile even on the
tier-1 core slice.

## Validation Workflow

Use local checks as the release gate before considering a deploy:

```bash
ruff check src tests scripts
pytest -m "not live and not slow" --tb=short -q
./leanEconAPI_venv/bin/python src/mcp_smoke_test.py
./leanEconAPI_venv/bin/python scripts/production_smoke.py --base-url https://leaneconapi-production.up.railway.app --poll-interval 1 --max-polls 10
docker build .
```

For API changes, also sanity-check `tests/test_api_smoke.py`.

Manual frontend coordination check:

- confirm preamble-backed Explore-to-Pipeline handoffs preserve
  `preamble_names`
- as observed on 2026-03-25 in the Lovable demo, `Preambles -> Use 1 in
  Pipeline` preserved `crra_utility`, while the theorem-card `Pipeline` action
  for `CRRA Relative Risk Aversion` populated the claim text without visibly
  preloading the same preamble context
