# LeanEcon API — Endpoint reference

All endpoints are under `/api/v1/`. Content-Type is `application/json` for all POST requests.

---

## POST /api/v1/classify

Pre-screen a claim before formalization.

**Request:**
```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma."
}
```

**Response (200):**
```json
{
  "cleaned_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma.",
  "category": "ALGEBRAIC",
  "formalizable": true,
  "reason": null,
  "is_raw_lean": false,
  "error_code": "none",
  "definitions_needed": null,
  "preamble_matches": [],
  "suggested_reformulation": null
}
```

**Category values:**
- `RAW_LEAN` — Input is already Lean code. Skip formalize, go to verify.
- `ALGEBRAIC` — Pure algebraic claim. Proceed to formalize.
- `DEFINABLE` — Needs economic definitions. Check `preamble_matches` for available ones. Proceed to formalize with those preamble names.
- `REQUIRES_DEFINITIONS` — Cannot be formalized. Show `reason` to user.

**DEFINABLE example response:**
```json
{
  "cleaned_claim": "Cobb-Douglas output elasticity with respect to capital equals alpha.",
  "category": "DEFINABLE",
  "formalizable": true,
  "reason": "Needs Cobb-Douglas production function definition.",
  "is_raw_lean": false,
  "error_code": "none",
  "definitions_needed": "Cobb-Douglas production function definition.",
  "preamble_matches": ["cobb_douglas_2factor"],
  "suggested_reformulation": "This claim requires defining: Two-factor Cobb-Douglas production function. LeanEcon has built-in definitions for these. Proceed to formalization and the definitions will be included automatically."
}
```

**Error (422):** `raw_claim` is blank or empty after cleaning.

---

## POST /api/v1/formalize

Convert a claim into a Lean 4 theorem with `:= by sorry`.

**Request:**
```json
{
  "raw_claim": "Under CRRA utility, relative risk aversion is constant and equal to gamma.",
  "preamble_names": ["crra_utility"]
}
```

`preamble_names` is optional. When provided, injects the named preamble definitions into the theorem file. Use values from classify's `preamble_matches` or from the preamble catalog.

**Response (200) — success:**
```json
{
  "success": true,
  "theorem_code": "import Mathlib\nimport LeanEcon.Preamble.Consumer.CRRAUtility\nopen Real\n\ntheorem crra_constant_rra (γ : ℝ) (hγ : γ > 0) (hγ1 : γ ≠ 1) (c : ℝ) (hc : c > 0) :\n    -c * (-γ * c⁻¹) = γ := by\n  sorry",
  "attempts": 1,
  "errors": [],
  "formalization_failed": false,
  "failure_reason": null,
  "error_code": "none",
  "preamble_used": ["crra_utility"],
  "diagnosis": null,
  "suggested_fix": null,
  "fixable": null
}
```

**Response (200) — failure:**
```json
{
  "success": false,
  "theorem_code": "import Mathlib\n-- FORMALIZATION_FAILED\n-- Reason: Requires competitive equilibrium framework.",
  "attempts": 0,
  "errors": [],
  "formalization_failed": true,
  "failure_reason": "Requires competitive equilibrium framework.",
  "error_code": "formalization_unformalizable",
  "preamble_used": [],
  "diagnosis": null,
  "suggested_fix": null,
  "fixable": null
}
```

When `success` is false but `formalization_failed` is also false, the system tried but sorry-validation failed. Check `diagnosis` and `suggested_fix` for repair hints.

**Raw Lean bypass:** If `raw_claim` contains `import Mathlib` or `:= by sorry`, it's returned unchanged with `attempts: 0`.

---

## POST /api/v1/verify

Queue a proof generation + verification job. **Returns HTTP 202, NOT 200.**

Each verify job is isolated: proving and final Lean verification use per-run
temporary files such as `AgenticProof_<id>.lean`, so concurrent jobs do not
overwrite a shared `Proof.lean`.

**Request:**
```json
{
  "theorem_code": "import Mathlib\nopen Real\n\ntheorem crra_constant_rra (γ : ℝ) (hγ : γ > 0) (hγ1 : γ ≠ 1) (c : ℝ) (hc : c > 0) :\n    -c * (-γ * c⁻¹) = γ := by\n  sorry",
  "explain": true
}
```

**Requirements:**
- `theorem_code` must contain a `theorem`, `lemma`, or `example` declaration
- `theorem_code` must contain `:= by` and `sorry`
- `explain: true` adds a natural language explanation to the final result

**Verification behavior:**
- The agentic prover edits its own working file.
- Final Lean acceptance is checked on an isolated per-run temp file with `lake env lean`.
- The endpoint always returns a queued job immediately; use polling or SSE for progress.

**Response (202):**
```json
{
  "job_id": "8edb1a2b-3cf3-4b59-9a0a-9f4b4655c9d6",
  "status": "queued"
}
```

**Error (422):** `theorem_code` doesn't look like a formalized Lean proof stub.

---

## GET /api/v1/jobs/{job_id}

Poll job status.

**Response (200):**
```json
{
  "job_id": "8edb1a2b-...",
  "status": "completed",
  "result": {
    "success": true,
    "lean_code": "import Mathlib\nopen Real\n\ntheorem crra_constant_rra ... := by\n  field_simp [ne_of_gt hc]",
    "errors": [],
    "warnings": [],
    "proof_strategy": "Use field_simp to clear the inverse, then the goal closes.",
    "proof_tactics": "field_simp [ne_of_gt hc]",
    "theorem_statement": "...",
    "formalization_attempts": 0,
    "formalization_failed": false,
    "failure_reason": null,
    "output_lean": null,
    "proof_generated": true,
    "phase": "verified",
    "elapsed_seconds": 63.2,
    "from_cache": false,
    "partial": false,
    "stop_reason": null,
    "axiom_info": {
      "axioms": ["propext", "Classical.choice"],
      "sound": true,
      "has_sorry_ax": false,
      "nonstandard_axioms": []
    },
    "error_code": "none",
    "explanation": "## What was formalized\n...",
    "explanation_generated": true
  },
  "error": null
}
```

**Status values:** `queued`, `running`, `completed`, `failed`

When `status` is `failed`, `error` contains the exception message and `result` is null.

**Error (404):** Job not found or expired (TTL: 1 hour).

---

## GET /api/v1/jobs/{job_id}/stream

Server-Sent Events stream for real-time progress.

**Response:** `Content-Type: text/event-stream`

```
data: {"type":"progress","stage":"formalize","message":"Calling Leanstral...","status":"running"}

data: {"type":"progress","stage":"agentic_run","message":"Leanstral proving loop started...","status":"running"}

data: {"type":"complete","status":"completed"}
```

**Event fields:**
- `type`: `progress` or `complete`
- `stage`: Pipeline stage name (progress events only)
- `message`: Human-readable text (progress events only)
- `status`: `running`, `done`, `error`, `completed`, `failed`
- `error`: Present on failed complete events

**Keepalive:** `: keepalive\n\n` comments every ~1 second during idle periods.

**Already-completed jobs:** Return a single `complete` event immediately.

**Typical progress stages:** `parse`, `formalize`, `prover_dispatch`,
`agentic_init`, `agentic_setup`, `agentic_run`, `agentic_check`,
`agentic_verify`, `cache`, `explain`

---

## POST /api/v1/explain

Generate a natural language explanation for any pipeline outcome.

**Request:**
```json
{
  "original_claim": "Under CRRA utility, RRA equals gamma.",
  "theorem_code": "import Mathlib\n...",
  "verification_result": {
    "success": true,
    "proof_generated": true,
    "formalization_failed": false
  }
}
```

All fields except `original_claim` are optional. Pass whichever artifacts you have. Can also accept `classification_result` or `formalization_result`.

**Response (200):**
```json
{
  "explanation": "## What was formalized\n...",
  "generated": true,
  "error_code": "none"
}
```

`generated: false` means the LLM explanation service timed out and a canned fallback was returned.

---

## GET /api/v1/metrics

Aggregate stats from the evaluation log.

**Response (200):**
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

---

## GET /api/v1/cache/stats

```json
{ "size": 4 }
```

## DELETE /api/v1/cache

```json
{ "status": "cleared" }
```

## GET /health

```json
{ "status": "ok" }
```
