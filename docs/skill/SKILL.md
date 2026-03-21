---
name: leanecon-api
description: "Integration guide for the LeanEcon formal verification API. Use this skill whenever building frontend applications, agents, or services that connect to LeanEcon for mathematical claim verification. Triggers when: building a UI for theorem verification, connecting to the LeanEcon API, implementing SSE streaming from a verification backend, displaying Lean 4 proof results, creating forms that accept mathematical claims (LaTeX, natural language, or raw Lean), handling async job polling patterns, or building any application that needs to classify/formalize/verify mathematical statements. Also use when the user mentions LeanEcon, formal verification frontend, proof verification UI, or Lean 4 integration."
---

# LeanEcon API Integration Skill

LeanEcon is a headless formal verification microservice that takes mathematical claims (natural language, LaTeX, or raw Lean 4) and produces machine-checked proofs using Lean 4 and Mathlib.

**Base URL:** `https://leaneconapi-production.up.railway.app`
**Interactive docs:** `{BASE_URL}/docs` (Swagger UI)
**OpenAPI schema:** `{BASE_URL}/openapi.json`

## Architecture overview

LeanEcon has a three-layer trust model that frontends should communicate to users:

1. **Stochastic layer** — Leanstral (LLM) generates candidate formalizations and proofs. May fail. Output quality varies.
2. **Human-in-the-loop** — The user reviews the formalized theorem before proving. This is where frontends add value.
3. **Deterministic layer** — Lean 4's kernel verifies the proof from axioms. If it passes, it's mathematically certified. Not LLM confidence — formal certainty.

## Core workflow (5 steps)

Every frontend should implement this sequence:

```
1. POST /api/v1/classify    → Is this claim in scope?
2. POST /api/v1/formalize   → Get a Lean theorem with sorry
3. [User reviews/edits]     → Frontend presents theorem for review
4. POST /api/v1/verify      → Returns 202 + job_id (async)
5. GET /api/v1/jobs/{id}/stream  → SSE progress events
   GET /api/v1/jobs/{id}         → Final result when complete
6. POST /api/v1/explain     → Natural language explanation (optional)
```

For detailed endpoint schemas, request/response examples, and SSE event formats, read `endpoints.md`.
For the preamble catalog (reusable economic definitions), read `preamble.md`.

## Critical integration patterns

### The async verify pattern

**This is the #1 source of frontend bugs.** Verify is NOT synchronous.

```
POST /api/v1/verify → HTTP 202 { "job_id": "...", "status": "queued" }
```

The proof takes 30-120 seconds. You MUST either:
- **Poll:** `GET /api/v1/jobs/{job_id}` every 2-3 seconds until `status` is `completed` or `failed`
- **Stream (preferred):** `GET /api/v1/jobs/{job_id}/stream` returns SSE events

NEVER block the UI waiting for verify to return. Show a progress timeline.

Under the hood, each verify job uses its own temporary Lean file for final
verification, so multiple concurrent jobs are safe. The API no longer depends
on routing every proof through a shared `Proof.lean`.

### SSE streaming for real-time progress

```javascript
const eventSource = new EventSource(`${BASE_URL}/api/v1/jobs/${jobId}/stream`);

eventSource.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === "progress") {
    // Update progress UI: data.stage, data.message, data.status
    // Common stages: "parse", "formalize", "prover_dispatch",
    // "agentic_init", "agentic_setup", "agentic_run",
    // "agentic_check", "agentic_verify", "cache", "explain"
    return;
  }
  
  if (data.type === "complete") {
    eventSource.close();
    // Fetch full result: GET /api/v1/jobs/${jobId}
  }
};

eventSource.onerror = () => {
  eventSource.close();
  // Fall back to polling
};
```

SSE events do NOT include the final verification payload. After receiving `type: "complete"`, fetch `GET /api/v1/jobs/{job_id}` for the full result.

### Input classification determines the UI flow

The classify response tells the frontend what to do next:

| `category` | `formalizable` | Frontend action |
|---|---|---|
| `RAW_LEAN` | `true` | Skip formalize, go straight to verify |
| `ALGEBRAIC` | `true` | Proceed to formalize normally |
| `DEFINABLE` | `true` | Show `preamble_matches`, proceed to formalize with those preamble names |
| `REQUIRES_DEFINITIONS` | `false` | Show rejection reason, suggest reformulation |

### Preamble-aware formalization

When classify returns `preamble_matches`, pass them to formalize:

```json
POST /api/v1/formalize
{
  "raw_claim": "Cobb-Douglas output elasticity equals alpha",
  "preamble_names": ["cobb_douglas_2factor"]
}
```

The 29 available preamble names and their domains are listed in `preamble.md`.

### Handling verification results

The job result contains a `phase` field that determines the UI state:

| `phase` | Meaning | UI treatment |
|---|---|---|
| `verified` | Lean kernel accepted the proof | Show success with green indicator. This is a machine-checked proof. |
| `proved` | A proof was generated but Lean rejected it | Show warning. The prover tried but the proof had a flaw. Offer retry. |
| `failed` | No valid proof was found | Show failure. Distinguish formalization failure vs proving failure via `formalization_failed` field. |

### Axiom soundness

When verification succeeds, the result may include `axiom_info`:

```json
{
  "axioms": ["propext", "Classical.choice", "Quot.sound"],
  "sound": true,
  "has_sorry_ax": false,
  "nonstandard_axioms": []
}
```

- `sound: true` + `has_sorry_ax: false` = fully verified
- `has_sorry_ax: true` = proof is NOT sound despite compilation (show warning)
- `nonstandard_axioms` lists anything beyond the standard three

### Error codes

Every response includes `error_code` for programmatic error handling:

- `none` — Success
- `classification_rejected` — Claim needs definitions not in scope
- `formalization_failed` — Could not produce valid Lean
- `formalization_unformalizable` — Claim is out of Mathlib scope
- `proof_not_found` — Valid theorem, no proof found
- `proof_timeout` — Prover timed out (check `partial` field)
- `verification_rejected` — Lean rejected the proof
- `verification_sorry` — Proof contains sorry

## UX best practices

### What to show during the 30-120s verification wait

Map SSE `stage` values to user-friendly labels:

| `stage` | User-facing label |
|---|---|
| `formalize` | "Translating to formal mathematics..." |
| `agentic_init` | "Setting up the proof environment..." |
| `agentic_setup` | "Connecting to Lean 4..." |
| `agentic_run` | "Searching for a proof..." |
| `prover_dispatch` | "Selecting the prover backend..." |
| `agentic_verify` | "Verifying the final proof in Lean..." |
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

## Limitations to communicate honestly

- Verification is stochastic. The same claim may pass on one run and fail on the next. Offer retry buttons.
- Currently strongest on algebraic identities (field arithmetic, ring algebra). Claims involving Real.rpow with variable exponents are brittle.
- Claims requiring equilibrium concepts, welfare theorems, fixed-point arguments, or measure theory are correctly rejected but cannot be verified.
- The Leanstral model is a labs endpoint — not a permanent production API.
- Each verification run takes 30-120 seconds. Plan UX accordingly.

## CORS

The API allows all origins (`*`). No authentication is currently required at the API level — auth should be implemented at the frontend layer.

## Operational endpoints

- `GET /health` → `{"status": "ok"}`
- `GET /api/v1/metrics` → Aggregate verification stats from eval log
- `GET /api/v1/cache/stats` → `{"size": N}`
- `DELETE /api/v1/cache` → Clear verified result cache
