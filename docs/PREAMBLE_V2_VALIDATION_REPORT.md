# Preamble V2 Validation Report

Date: 2026-03-27

## Scope

This report covers the theorem-first rebuild of the LeanEcon preamble library,
the new `strong` versus `compatibility-only` selection policy, the prompt and
retrieval integration changes, and the new benchmark suite
`benchmarks/tier1_preamble_strong.jsonl`.

## Code Areas Updated

- Lean preamble modules under `lean_workspace/LeanEcon/Preamble/`
- Preamble registry and routing in `src/preamble_library.py`
- Retrieval context building in `src/formalization_search.py`
- Formalizer prompting in `src/prompts.py`
- Catalog generation in `scripts/generate_preamble_catalog.py`
- Tests in `tests/test_formalizer.py`, `tests/test_formalization_search.py`,
  and `tests/test_generate_preamble_catalog.py`
- New benchmark suite in `benchmarks/tier1_preamble_strong.jsonl`

## Validation Summary

### Lean Builds

- `lake build LeanEcon.Preamble`
  - Result: passed
- `lake build LeanEcon`
  - Result: passed

### Python Test Suite

- `./leanEconAPI_venv/bin/python -m pytest -q -m 'not live'`
  - Result: `244 passed, 13 deselected in 8.10s`
- `./leanEconAPI_venv/bin/python -m pytest tests/test_agentic_examples.py -q`
  - Result: `3 passed in 341.92s`
  - Note: this run required network access because it exercises the live agentic
    prover path.

### Focused Rebuild Tests

- `./leanEconAPI_venv/bin/python -m pytest tests/test_formalizer.py tests/test_formalization_search.py tests/test_generate_preamble_catalog.py -q`
  - Result: `65 passed in 0.90s`

## Deterministic Before/After Comparison

Baseline comparison used a temporary clean `HEAD` worktree. The worktree was
removed after measurement. These numbers are local routing-and-retrieval
metrics, not provider-dependent prover scores.

### tier0_smoke.jsonl

- Baseline auto-hit rate: `1/1`
- Current auto-hit rate: `1/1`
- Baseline advisory-hit rate: `1/1`
- Current advisory-hit rate: `1/1`
- Baseline average candidate identifiers: `0.0`
- Current average candidate identifiers: `3.0`
- Baseline average search terms: `0.0`
- Current average search terms: `2.0`

### tier1_core.jsonl

- Baseline auto-hit rate: `6/6`
- Current auto-hit rate: `4/6`
- Baseline advisory-hit rate: `6/6`
- Current advisory-hit rate: `6/6`
- Baseline average candidate identifiers: `0.5`
- Current average candidate identifiers: `4.67`
- Baseline average search terms: `0.5`
- Current average search terms: `2.83`

Interpretation:

- The auto-hit drop is intentional. Thin wrappers such as `solow_steady_state`
  and `phillips_curve` are now `compatibility-only`, so they remain discoverable
  in advisory matches but are no longer auto-selected as if they were theorem-rich.

### tier1_preamble_strong.jsonl

- Baseline auto-hit rate: `7/9`
- Current auto-hit rate: `9/9`
- Baseline advisory-hit rate: `8/9`
- Current advisory-hit rate: `9/9`
- Baseline average candidate identifiers: `2.11`
- Current average candidate identifiers: `7.33`
- Baseline average search terms: `2.44`
- Current average search terms: `5.22`

Interpretation:

- The rebuilt preamble materially improves routing quality on the theorem-bearing
  suite it was designed for.
- Retrieval context is also substantially richer, which should help both
  formalization and downstream proving once provider-backed benchmarking is run.

## Notes On Provider-Backed Benchmarks

I attempted to run the benchmark harness directly via
`scripts/run_benchmark.py`, but the in-turn run did not yield a completed
benchmark artifact before the session timing constraints became binding.

Because of that, this validation package includes:

- fully green local Lean builds,
- green local non-live Python tests,
- green live agentic prover examples under network access, and
- deterministic baseline-vs-current routing/retrieval comparisons.

It does not yet include a completed end-to-end benchmark-harness report for the
new suite.

## Push Readiness

Status: ready to push with one caveat.

Caveat:

- If release criteria require a provider-backed benchmark-harness artifact, run
  `scripts/run_benchmark.py` separately in an environment with stable network
  access and archive the resulting report alongside this memo.
