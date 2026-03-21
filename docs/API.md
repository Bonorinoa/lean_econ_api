# LeanEcon API Guide

LeanEcon exposes a multi-step REST API designed for frontend code and coding
agents. The safest workflow is:

1. `POST /api/classify`
2. `POST /api/formalize`
3. Optionally edit the returned `theorem_code`
4. `POST /api/verify`

The generated OpenAPI schema is available from FastAPI at `/openapi.json`, and
the interactive docs are available at `/docs`.

## Workflow

### 1. Classify

Use `POST /api/classify` to decide whether a claim looks formalizable before
spending formalization/proving effort.

Request:

```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma."
}
```

Response fields:

- `cleaned_claim`: normalized claim text after light preprocessing
- `category`: one of `RAW_LEAN`, `ALGEBRAIC`, `REQUIRES_DEFINITIONS`
- `formalizable`: quick yes/no signal for whether to continue
- `reason`: rejection explanation for out-of-scope claims
- `is_raw_lean`: whether the input already looked like Lean code

Interpretation:

- `RAW_LEAN`: skip directly to `POST /api/verify`
- `ALGEBRAIC`: continue to `POST /api/formalize`
- `REQUIRES_DEFINITIONS`: stop or ask a human to reformulate the claim

### 2. Formalize

Use `POST /api/formalize` to turn natural language or LaTeX into a Lean theorem
file containing `:= by sorry`.

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

If `raw_claim` already looks like Lean and contains a proof stub, this endpoint
passes it through unchanged with `attempts = 0`.

### 3. Verify

Use `POST /api/verify` to run proof generation plus final Lean verification.

Request:

```json
{
  "theorem_code": "import Mathlib\nopen Real\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  sorry"
}
```

Important request rules:

- `theorem_code` must look like a Lean theorem/lemma/example
- it must still contain `:= by sorry`
- LeanEcon always uses the agentic prover for verify requests

Important response fields:

- `success`: whether Lean accepted the final proof
- `phase`: one of `verified`, `proved`, `failed`
- `lean_code`: final Lean file produced by the proving run
- `proof_strategy`: high-level proof plan
- `proof_tactics`: tactic script or tactics summary
- `errors` / `warnings`: Lean diagnostics
- `elapsed_seconds`: pipeline runtime

Phase meanings:

- `verified`: Lean accepted the proof
- `proved`: a proof was generated, but Lean rejected it
- `failed`: the pipeline did not reach a valid proof

## Health

`GET /health` returns:

```json
{
  "status": "ok"
}
```

Use it for local liveness checks or container orchestration.

## Error handling

- `422` means the request payload was blank or structurally invalid for the
  endpoint
- `500` means an unexpected internal failure occurred in classification,
  formalization, or verification

## Example agent flow

An agent integrating LeanEcon should usually follow this sequence:

1. Send the original user input to `POST /api/classify`
2. If `category == "REQUIRES_DEFINITIONS"`, stop and surface `reason`
3. If `category == "RAW_LEAN"`, send the Lean string directly to `POST /api/verify`
4. Otherwise call `POST /api/formalize`
5. Let a human or agent edit `theorem_code` if needed
6. Send the final theorem text to `POST /api/verify`
7. Use `success`, `phase`, `errors`, and `lean_code` to render the result
