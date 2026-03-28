# LeanEcon Benchmark Report

Generated: 2026-03-28T18:10:26.077302+00:00
Benchmark file: `/Users/bonorinoa/Desktop/Github_Repositories/lean_econ_api/benchmarks/tier1_core_selected_full.jsonl`
Mode: `full`
Repetitions: `1`
Cache enabled: `False`

## Aggregate Lane Summary

| Lane | Cases | Attempts | pass@1 | pass@3 | pass@5 | Partial attempts | Partial rate | p50 ms | p95 ms | Cache hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw_claim -> full API | 3 | 3 | 0.000 | n/a | n/a | 2 | 0.667 | 211581.3 | 271994.6 | 0 |
| theorem_stub -> verify | 3 | 3 | 1.000 | n/a | n/a | 0 | 0.000 | 148043.8 | 181732.1 | 0 |
| raw_lean -> verify | 3 | 3 | 1.000 | n/a | n/a | 0 | 0.000 | 146810.5 | 149672.7 | 0 |

## Aggregate Tier Summary

### tier1_core

| Lane | Cases | Attempts | pass@1 | Partial rate | p95 ms | Semantic >=4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| raw_claim -> full API | 3 | 3 | 0.000 | 0.667 | 271994.6 | 1.000 |
| theorem_stub -> verify | 3 | 3 | 1.000 | 0.000 | 181732.1 | n/a |
| raw_lean -> verify | 3 | 3 | 1.000 | 0.000 | 149672.7 | n/a |


### raw_claim -> full API

- Failure stages: {'agentic_verify': 2, 'formalize': 1}
- Error codes: {'verification_rejected': 2, 'formalization_failed': 1}
- Stop reasons: {'append_round_cap': 2}
- Partial attempts/rate: 2 / 0.667
- Validation methods: {'lake_env_lean': 3}
- Validation fallback reasons: {'lean_run_code_unavailable': 3}
- Repair buckets: {'semantic_mismatch': 1}
- Retrieval sources: {'preamble': 3, 'curated': 1}
- Reasoning presets: {'medium': 2}
- Timeout scopes: (none)
- Budget usage (p95): append_rounds=24, api_round_trips=25, tool_calls=25, search_tool_calls=0.9
- Semantic alignment: {'graded_attempts': 2, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 2}, 'trivialization_flag_counts': {}}

### theorem_stub -> verify

- Failure stages: (none)
- Error codes: {'none': 3}
- Stop reasons: {'proof_complete': 3}
- Partial attempts/rate: 0 / 0.000
- Validation methods: (none)
- Validation fallback reasons: (none)
- Repair buckets: (none)
- Retrieval sources: (none)
- Reasoning presets: {'medium': 3}
- Timeout scopes: (none)
- Budget usage (p95): append_rounds=14.5, api_round_trips=15.5, tool_calls=14.5, search_tool_calls=0
- Semantic alignment: {'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}

### raw_lean -> verify

- Failure stages: (none)
- Error codes: {'none': 3}
- Stop reasons: {'proof_complete': 3}
- Partial attempts/rate: 0 / 0.000
- Validation methods: (none)
- Validation fallback reasons: (none)
- Repair buckets: (none)
- Retrieval sources: (none)
- Reasoning presets: {'medium': 3}
- Timeout scopes: (none)
- Budget usage (p95): append_rounds=6, api_round_trips=7, tool_calls=6, search_tool_calls=0
- Semantic alignment: {'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}

## Per-Case Summary

### t1_crra_rra

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: Under CRRA utility u(c) = c^(1-gamma)/(1-gamma), relative risk aversion simplifies to gamma.
- Preambles: crra_utility
- raw_claim -> full API: pass@1=False, pass@3=None, pass@5=None, partial_attempts=1, partial_rate=1.0, p50=278707.2 ms, p95=278707.2 ms, failure_stages={'agentic_verify': 1}, error_codes={'verification_rejected': 1}, stop_reasons={'append_round_cap': 1}, validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), reasoning_presets={'medium': 1}, timeout_scopes=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 1}, 'trivialization_flag_counts': {}}
- theorem_stub -> verify: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=146004.6 ms, p95=146004.6 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons={'proof_complete': 1}, validation_methods=(none), validation_fallbacks=(none), repair_buckets=(none), reasoning_presets={'medium': 1}, timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}
- raw_lean -> verify: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=146810.5 ms, p95=146810.5 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons={'proof_complete': 1}, validation_methods=(none), validation_fallbacks=(none), repair_buckets=(none), reasoning_presets={'medium': 1}, timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}

### t1_marshallian_demand_good1

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: For Cobb-Douglas preferences, Marshallian demand for good 1 is alpha * m / p1.
- Preambles: marshallian_demand
- raw_claim -> full API: pass@1=False, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=53291.0 ms, p95=53291.0 ms, failure_stages={'formalize': 1}, error_codes={'formalization_failed': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets={'semantic_mismatch': 1}, reasoning_presets=(none), timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}
- theorem_stub -> verify: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=185475.3 ms, p95=185475.3 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons={'proof_complete': 1}, validation_methods=(none), validation_fallbacks=(none), repair_buckets=(none), reasoning_presets={'medium': 1}, timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}
- raw_lean -> verify: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=149990.7 ms, p95=149990.7 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons={'proof_complete': 1}, validation_methods=(none), validation_fallbacks=(none), repair_buckets=(none), reasoning_presets={'medium': 1}, timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}

### t1_cobb_douglas_elasticity

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: For a two-factor Cobb-Douglas production function, output elasticity with respect to capital is alpha.
- Preambles: cobb_douglas_2factor
- raw_claim -> full API: pass@1=False, pass@3=None, pass@5=None, partial_attempts=1, partial_rate=1.0, p50=211581.3 ms, p95=211581.3 ms, failure_stages={'agentic_verify': 1}, error_codes={'verification_rejected': 1}, stop_reasons={'append_round_cap': 1}, validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), reasoning_presets={'medium': 1}, timeout_scopes=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 1}, 'trivialization_flag_counts': {}}
- theorem_stub -> verify: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=148043.8 ms, p95=148043.8 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons={'proof_complete': 1}, validation_methods=(none), validation_fallbacks=(none), repair_buckets=(none), reasoning_presets={'medium': 1}, timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}
- raw_lean -> verify: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=137165.5 ms, p95=137165.5 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons={'proof_complete': 1}, validation_methods=(none), validation_fallbacks=(none), repair_buckets=(none), reasoning_presets={'medium': 1}, timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}
