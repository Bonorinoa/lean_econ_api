# LeanEcon API Guide

LeanEcon exposes a versioned REST API for classification, formalization, proof
generation, and Lean verification. The generated OpenAPI schema is available at
`/openapi.json`, and the interactive docs are available at `/docs`.

## Recommended workflow

1. `POST /api/v1/classify`
2. `POST /api/v1/formalize`
3. Optionally edit the returned `theorem_code`
4. `POST /api/v1/verify`
5. Track progress with either:
   - `GET /api/v1/jobs/{job_id}`
   - `GET /api/v1/jobs/{job_id}/stream`

## 1. Classify

Use `POST /api/v1/classify` to decide whether a claim looks formalizable before
spending proving effort.

Request:

```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma."
}
```

Important response fields:

- `cleaned_claim`: normalized claim text after lightweight cleaning
- `category`: one of `RAW_LEAN`, `ALGEBRAIC`, `DEFINABLE`, `REQUIRES_DEFINITIONS`
- `formalizable`: quick yes/no signal for whether to continue
- `reason`: rejection explanation for out-of-scope claims
- `is_raw_lean`: whether the input already looked like Lean code

Interpretation:

- `RAW_LEAN`: skip directly to `POST /api/v1/verify`
- `ALGEBRAIC` or `DEFINABLE`: continue to `POST /api/v1/formalize`
- `REQUIRES_DEFINITIONS`: stop or ask a human to reformulate the claim

## 2. Formalize

Use `POST /api/v1/formalize` to turn natural language or LaTeX into a Lean
theorem file containing `:= by sorry`.

Request:

```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma."
}
```

Important response fields:

- `success`: whether the theorem compiled with `sorry`
- `theorem_code`: full Lean file content to review or edit
- `attempts`: number of formalization/repair attempts used
- `formalization_failed`: whether the claim was rejected as out of scope
- `failure_reason`: explanation for a formalization rejection
- `preamble_used`: injected preamble definitions, if any

If `raw_claim` already looks like Lean and contains a proof stub, this endpoint
passes it through unchanged with `attempts = 0`.

## 3. Verify

Use `POST /api/v1/verify` to queue proof generation plus final Lean
verification.

Request:

```json
{
  "theorem_code": "import Mathlib\nopen Real\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  sorry"
}
```

Important request rules:

- `theorem_code` must look like a Lean theorem/lemma/example
- it must still contain `:= by sorry`
- the endpoint responds immediately with HTTP `202`

Response:

```json
{
  "job_id": "8edb1a2b-3cf3-4b59-9a0a-9f4b4655c9d6",
  "status": "queued"
}
```

After queueing the job, either poll `GET /api/v1/jobs/{job_id}` or stream
`GET /api/v1/jobs/{job_id}/stream`.

Important final result fields from `GET /api/v1/jobs/{job_id}`:

- `success`: whether Lean accepted the final proof
- `phase`: one of `verified`, `proved`, `failed`
- `lean_code`: final Lean file produced by the proving run
- `proof_strategy`: high-level proof plan
- `proof_tactics`: tactic script or tactics summary
- `errors` / `warnings`: Lean diagnostics
- `elapsed_seconds`: pipeline runtime
- `from_cache`: whether the result came from the verified-result cache
- `partial`: whether the prover timed out and returned partial output
- `axiom_info`: optional axiom usage metadata from final verification

Phase meanings:

- `verified`: Lean accepted the proof
- `proved`: a proof was generated, but Lean rejected it
- `failed`: the pipeline did not reach a valid proof

## SSE streaming

`GET /api/v1/jobs/{job_id}/stream` returns a Server-Sent Events stream with
`Content-Type: text/event-stream`.

Each event is emitted as a single JSON object on a `data:` line:

```text
data: {"type":"progress","stage":"formalize","message":"Calling Leanstral...","status":"running"}

data: {"type":"progress","stage":"agentic_run","message":"Leanstral proving loop started...","status":"running"}

data: {"type":"complete","status":"completed"}
```

Event fields:

- `type`: `progress` or `complete`
- `stage`: pipeline stage name for progress events
- `message`: human-readable progress text for progress events
- `status`: stage/job status such as `running`, `done`, `error`, `completed`, `failed`

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
  formalization, verification, or explanation
