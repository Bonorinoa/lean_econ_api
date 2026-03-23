# Lovable Prompt: LeanEcon Demo Runtime and UX

Improve the LeanEcon demo without changing the current public API contract.

Treat formalization as the slowest stage and design for patient, transparent waiting. Show a persistent stage timeline from click to completion, include elapsed time per stage, and make raw Lean an explicit mode toggle because it is materially faster and more reliable than plain-English input.

Do not promise fixed speedups unless they were re-measured against the live API.

For verification:

- Call `POST /api/v1/verify` with `explain: false`
- Open `GET /api/v1/jobs/{job_id}/stream` immediately for SSE progress
- Also fetch `GET /api/v1/jobs/{job_id}` once right after job creation so the UI can hydrate `current_stage` and `stage_timings` even if early SSE events were missed
- Keep a polling fallback so the UI can still show real stage state instead of a generic spinner

After verification completes, call `POST /api/v1/explain` in the background so explanation latency never blocks the verified result.

UX requirements:

- Make raw Lean a first-class input mode, not a hidden advanced path
- Warn users that plain-English formalization is slower and less reliable than raw Lean
- Surface formalization, proving, verification, and explanation as separate stages
- Show elapsed time and current status for each stage
- Persist partial progress if the user refreshes or reconnects
- Add benchmark-backed example inputs drawn from `tier0_smoke` and `tier1_core`

Copy guidance:

- Avoid implying that the system covers arbitrary advanced economics
- Be explicit that successful verification is deterministic Lean kernel acceptance
- Distinguish formalization failure from proof failure
