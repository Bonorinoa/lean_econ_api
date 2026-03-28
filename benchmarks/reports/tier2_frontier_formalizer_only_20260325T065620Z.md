# LeanEcon Benchmark Report

Generated: 2026-03-25T06:56:20.146168+00:00
Benchmark file: `/Users/bonorinoa/Desktop/Github_Repositories/lean_econ_api/benchmarks/tier2_frontier.jsonl`
Mode: `formalizer-only`
Repetitions: `1`
Cache enabled: `False`

## Aggregate Lane Summary

| Lane | Cases | Attempts | pass@1 | pass@3 | pass@5 | p50 ms | p95 ms | Cache hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw_claim -> formalizer-only gate | 3 | 3 | 0.667 | n/a | n/a | 36880.7 | 62953.6 | 0 |

## Aggregate Tier Summary

### tier2_frontier

| Lane | Cases | Attempts | pass@1 | p95 ms | Semantic >=4 |
| --- | ---: | ---: | ---: | ---: | ---: |
| raw_claim -> formalizer-only gate | 3 | 3 | 0.667 | 62953.6 | 1.000 |


### raw_claim -> formalizer-only gate

- Failure stages: {'formalize': 1}
- Error codes: {'none': 2, 'formalization_failed': 1}
- Stop reasons: (none)
- Validation methods: {'lake_env_lean': 3}
- Validation fallback reasons: {'lean_run_code_unavailable': 3}
- Repair buckets: {'semantic_mismatch': 1, 'syntax_notation': 1}
- Retrieval sources: {'curated': 5, 'preamble': 1}
- Semantic alignment: {'graded_attempts': 2, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 2}, 'trivialization_flag_counts': {}}

## Per-Case Summary

### t2_contraction_mapping_fixed_point

- Tier: tier2_frontier
- Expected category: MATHLIB_NATIVE
- Raw claim: A contraction mapping on a complete metric space has a unique fixed point.
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, p50=65850.6 ms, p95=65850.6 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 1}, 'trivialization_flag_counts': {}}

### t2_extreme_value_repair

- Tier: tier2_frontier
- Expected category: DEFINABLE
- Raw claim: A strictly concave function attains a maximum on a compact set.
- raw_claim -> formalizer-only gate: pass@1=False, pass@3=None, pass@5=None, p50=36880.7 ms, p95=36880.7 ms, failure_stages={'formalize': 1}, error_codes={'formalization_failed': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets={'semantic_mismatch': 1}, semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}

### t2_monotone_sequence_converges

- Tier: tier2_frontier
- Expected category: MATHLIB_NATIVE
- Raw claim: A monotone sequence bounded above converges.
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, p50=33740.5 ms, p95=33740.5 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets={'syntax_notation': 1}, semantic_alignment={'graded_attempts': 1, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 1}, 'trivialization_flag_counts': {}}
