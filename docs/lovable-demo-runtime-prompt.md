# Lovable Prompt: LeanEcon Demo Runtime and UX

Improve the LeanEcon demo without changing the current public API contract.

Treat formalization as the slowest stage and design for patient, transparent waiting. Show a persistent stage timeline from click to completion, include elapsed time per stage, and make raw Lean an explicit mode toggle because it is materially faster and more reliable than plain-English input.

Do not promise fixed speedups unless they were re-measured against the live API.

Quote policy:

- Use only strict verbatim quotes with a stable public source URL.
- Do not use composites, paraphrases, or stitched-together summaries as if they were direct quotations.
- If you cannot verify the exact wording on a stable public source page or PDF, omit the quote.
- Store attribution with enough detail to re-check it later: speaker, source title, publication/event, date if available, and URL.
- Prefer shorter exact pull quotes over long testimonial blocks.
- Current live landing-page testimonials should be treated as suspect until re-sourced; replace them before redeploying quote changes.

Verified source candidates for replacement testimonials:

- Terence Tao, "Machine assisted proof" PDF:
  `https://terrytao.wordpress.com/wp-content/uploads/2024/03/machine-assisted-proof-notices.pdf`
- Kevin Buzzard and Alex Kontorovich interview:
  `https://www.renaissancephilanthropy.org/news-and-insights/kevin-buzzard-and-alex-kontorovich-on-the-future-of-formal-mathematics-a-mathlib-initiative-interview`

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
- Update the pipeline examples/tests to cover two raw Lean statements and two natural-language statements
- Use meaningful button labels that match the real action being taken

Current live priorities to fix as of 2026-03-25:

- Keep the natural-language first action labeled `Formalize & Verify`. Live behavior now does run `/classify`, `/formalize`, and then `/verify` in one click, so preserve that honesty.
- Keep the raw-Lean first action wired directly to `POST /api/v1/verify`. The label `Verify with Lean 4` is now truthful and should stay that way.
- Preserve the immediate `GET /api/v1/jobs/{job_id}` hydration and `EventSource` streaming. Both are live and materially improve stage visibility.
- Keep explanation decoupled from verify latency. The app currently calls `POST /api/v1/explain` after verification rather than blocking the verified result.
- Treat the final verify payload as the source of truth for status badges. If the backend returns `success: true`, `phase: "verified"`, and `partial: false`, do not also show `Partial (timeout)` just because a warning mentions timeout cleanup.
- Preserve preamble context in Explore-to-Pipeline handoffs. When a theorem card is backed by a preamble entry, the pipeline payload should carry `preamble_names`, not only the claim text.
- Fix the observed theorem-card mismatch from 2026-03-25: `Preambles -> Use 1 in Pipeline` preserved `crra_utility`, but `CRRA Relative Risk Aversion -> Pipeline` did not visibly preload the same context.
- Fix state reset more thoroughly. On 2026-03-23, switching modes or changing example inputs could still leave stale stage chips, prior verification panels, and prior explanation text visible until the next run replaced them.
- Make raw-Lean mode scrub natural-language leftovers. When entering raw-Lean mode, the claim-analysis and explanation panels should not still show the previous natural-language run.
- Make natural-language mode scrub raw-Lean leftovers. When returning to natural-language mode, prior raw-Lean proofs and explanations should not remain attached to the new claim draft.
- Ensure example inputs match the public API contract. Raw-Lean examples should look like theorem stubs with `:= by sorry`, not like already-finished proofs, unless the frontend deliberately treats them as read-only demos rather than verify inputs.
- Continue improving first-user orientation. The mode toggle, warnings, and example chips are better now, but the app should still make it obvious that raw Lean is the faster and more reliable path today.
- Replace the current landing-page testimonial text with strictly sourced,
  verbatim quotes only. Do not keep any composite quote copy.

Example guidance:

- Raw Lean example 1 should be a trivial arithmetic theorem that is known to verify quickly, such as `1 + 1 = 2`.
- Raw Lean example 2 should be an economics-flavored benchmark-backed theorem that uses an exact hypothesis directly, such as a budget-equality theorem proved with `exact hspend`.
- Natural-language example 1 should cover the triangle inequality.
- Natural-language example 2 should cover the statement that all even natural numbers have the form `2n`.
- If the natural-language examples are used in automated UI tests, test the app flow and stage handling rather than assuming they verify successfully every time. Plain-English formalization is still the least reliable stage.

Copy guidance:

- Avoid implying that the system covers arbitrary advanced economics
- Be explicit that successful verification is deterministic Lean kernel acceptance
- Distinguish formalization failure from proof failure
