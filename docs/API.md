# LeanEcon API Guide

LeanEcon exposes a versioned REST API for claim classification, formalization,
proof generation, verification, explanation, cache inspection, and lightweight
run metrics.

Base docs:

- OpenAPI schema: `/openapi.json`
- Interactive docs: `/docs`

## Recommended v1 workflow

1. `POST /api/v1/classify`
2. `POST /api/v1/formalize`
3. Optionally edit the returned `theorem_code`
4. `POST /api/v1/verify`
5. Track the job with either:
   - `GET /api/v1/jobs/{job_id}`
   - `GET /api/v1/jobs/{job_id}/stream`
6. Optionally call `POST /api/v1/explain`

## 1. Classify

Use `POST /api/v1/classify` to decide whether the claim looks formalizable
before spending proving effort.

Request:

```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma."
}
```

Important response fields:

- `cleaned_claim`: normalized claim text after lightweight cleaning
- `category`: `RAW_LEAN`, `ALGEBRAIC`, `DEFINABLE`, or `REQUIRES_DEFINITIONS`
- `formalizable`: quick yes/no signal for whether to continue
- `reason`: rejection explanation for out-of-scope claims
- `definitions_needed`: missing concept description for `DEFINABLE` claims
- `preamble_matches`: reusable LeanEcon modules that may help formalization
- `suggested_reformulation`: optional reformulation hint
- `error_code`: machine-readable classifier outcome

Interpretation:

- `RAW_LEAN`: skip directly to `POST /api/v1/verify`
- `ALGEBRAIC`: continue to `POST /api/v1/formalize`
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

Queue response:

```json
{
  "job_id": "8edb1a2b-3cf3-4b59-9a0a-9f4b4655c9d6",
  "status": "queued"
}
```

### Polling jobs

Use `GET /api/v1/jobs/{job_id}` to read job status and final output.

Response fields:

- `job_id`: the same identifier returned by verify
- `status`: `queued`, `running`, `completed`, or `failed`
- `result`: final verify payload when completed
- `error`: exception text when failed

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
- `axiom_info`: optional axiom-usage metadata from final verification
- `explanation`: optional natural-language explanation when `explain=true`
- `explanation_generated`: whether the explanation was model-generated
- `error_code`: machine-readable verification outcome

`axiom_info` is only present when the final verification succeeded and axiom
checking was available. Its shape is:

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
`logs/runs.jsonl`.

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
