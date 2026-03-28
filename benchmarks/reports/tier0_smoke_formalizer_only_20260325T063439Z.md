# LeanEcon Benchmark Report

Generated: 2026-03-25T06:34:39.859572+00:00
Benchmark file: `/Users/bonorinoa/Desktop/Github_Repositories/lean_econ_api/benchmarks/tier0_smoke.jsonl`
Mode: `formalizer-only`
Repetitions: `1`
Cache enabled: `False`

## Aggregate Lane Summary

| Lane | Cases | Attempts | pass@1 | pass@3 | pass@5 | p50 ms | p95 ms | Cache hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw_claim -> formalizer-only gate | 3 | 3 | 1.000 | n/a | n/a | 16207.5 | 67017.1 | 0 |

## Aggregate Tier Summary

### tier0_smoke

| Lane | Cases | Attempts | pass@1 | p95 ms | Semantic >=4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| raw_claim -> formalizer-only gate | 3 | 3 | 1.000 | 67017.1 | 0.667 |


### raw_claim -> formalizer-only gate

- Failure stages: (none)
- Error codes: {'none': 3}
- Stop reasons: (none)
- Validation methods: {'lake_env_lean': 3}
- Validation fallback reasons: {'lean_run_code_unavailable': 3}
- Repair buckets: (none)
- Retrieval sources: {'preamble': 1}
- Semantic alignment: {'graded_attempts': 3, 'avg_score': 3.33, 'score_p50': 4.0, 'score_p95': 4.9, 'score_ge_4_rate': 0.667, 'verdict_counts': {'Wrong, vacuous, or auto-trivialized into something like A = A': 1, 'Mostly faithful, with only minor simplifications': 1, 'Faithful and non-trivial translation': 1}, 'trivialization_flag_counts': {'no_economic_content': 1, 'tautology': 1}}

## Per-Case Summary

### t0_one_plus_one

- Tier: tier0_smoke
- Expected category: ALGEBRAIC
- Raw claim: 1 + 1 = 2
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, p50=72662.6 ms, p95=72662.6 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 1.0, 'score_p50': 1.0, 'score_p95': 1.0, 'score_ge_4_rate': 0.0, 'verdict_counts': {'Wrong, vacuous, or auto-trivialized into something like A = A': 1}, 'trivialization_flag_counts': {'no_economic_content': 1, 'tautology': 1}}

### t0_budget_constraint

- Tier: tier0_smoke
- Expected category: ALGEBRAIC
- Raw claim: For a consumer with income m and prices p1, p2 spending all income, the budget equality p1 * x1 + p2 * x2 = m holds.
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, p50=15721.6 ms, p95=15721.6 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 4.0, 'score_p50': 4.0, 'score_p95': 4.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Mostly faithful, with only minor simplifications': 1}, 'trivialization_flag_counts': {}}

### t0_budget_set_membership

- Tier: tier0_smoke
- Expected category: DEFINABLE
- Raw claim: A two-good bundle with spending p1 * x1 + p2 * x2 less than or equal to income m lies in the budget set.
- Preambles: budget_set
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, p50=16207.5 ms, p95=16207.5 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 1}, 'trivialization_flag_counts': {}}
