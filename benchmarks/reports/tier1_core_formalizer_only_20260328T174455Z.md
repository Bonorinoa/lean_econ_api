# LeanEcon Benchmark Report

Generated: 2026-03-28T17:44:55.997121+00:00
Benchmark file: `/Users/bonorinoa/Desktop/Github_Repositories/lean_econ_api/benchmarks/tier1_core.jsonl`
Mode: `formalizer-only`
Repetitions: `1`
Cache enabled: `False`

## Aggregate Lane Summary

| Lane | Cases | Attempts | pass@1 | pass@3 | pass@5 | Partial attempts | Partial rate | p50 ms | p95 ms | Cache hits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| raw_claim -> formalizer-only gate | 6 | 6 | 0.667 | n/a | n/a | 0 | 0.000 | 32450.0 | 200912.5 | 0 |

## Aggregate Tier Summary

### tier1_core

| Lane | Cases | Attempts | pass@1 | Partial rate | p95 ms | Semantic >=4 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| raw_claim -> formalizer-only gate | 6 | 6 | 0.667 | 0.000 | 200912.5 | 0.750 |


### raw_claim -> formalizer-only gate

- Failure stages: {'formalize': 2}
- Error codes: {'none': 4, 'formalization_failed': 2}
- Stop reasons: (none)
- Partial attempts/rate: 0 / 0.000
- Validation methods: {'lake_env_lean': 6}
- Validation fallback reasons: {'lean_run_code_unavailable': 6}
- Repair buckets: {'semantic_mismatch': 2}
- Retrieval sources: {'preamble': 6, 'curated': 1}
- Reasoning presets: (none)
- Timeout scopes: (none)
- Budget usage (p95): append_rounds=n/a, api_round_trips=n/a, tool_calls=n/a, search_tool_calls=n/a
- Semantic alignment: {'graded_attempts': 4, 'avg_score': 3.75, 'score_p50': 4.5, 'score_p95': 5.0, 'score_ge_4_rate': 0.75, 'verdict_counts': {'Faithful and non-trivial translation': 2, 'Mostly faithful, with only minor simplifications': 1, 'Wrong, vacuous, or auto-trivialized into something like A = A.': 1}, 'trivialization_flag_counts': {'auto-trivialization': 1, 'no substantive claim': 1, 'tautology': 1}}

## Per-Case Summary

### t1_crra_rra

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: Under CRRA utility u(c) = c^(1-gamma)/(1-gamma), relative risk aversion simplifies to gamma.
- Preambles: crra_utility
- raw_claim -> formalizer-only gate: pass@1=False, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=250843.5 ms, p95=250843.5 ms, failure_stages={'formalize': 1}, error_codes={'formalization_failed': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets={'semantic_mismatch': 1}, reasoning_presets=(none), timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}

### t1_discount_factor_constant

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: With geometric discounting, the present value of a constant stream x for T periods is x * (1 - beta^T) / (1 - beta).
- Preambles: discount_factor
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=31592.3 ms, p95=31592.3 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), reasoning_presets=(none), timeout_scopes=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 1}, 'trivialization_flag_counts': {}}

### t1_marshallian_demand_good1

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: For Cobb-Douglas preferences, Marshallian demand for good 1 is alpha * m / p1.
- Preambles: marshallian_demand
- raw_claim -> formalizer-only gate: pass@1=False, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=51119.4 ms, p95=51119.4 ms, failure_stages={'formalize': 1}, error_codes={'formalization_failed': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets={'semantic_mismatch': 1}, reasoning_presets=(none), timeout_scopes=(none), semantic_alignment={'graded_attempts': 0, 'avg_score': None, 'score_p50': None, 'score_p95': None, 'score_ge_4_rate': None, 'verdict_counts': {}, 'trivialization_flag_counts': {}}

### t1_nkpc_identity

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: In the New Keynesian Phillips Curve, inflation equals beta times expected future inflation plus kappa times the output gap.
- Preambles: phillips_curve
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=22653.3 ms, p95=22653.3 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), reasoning_presets=(none), timeout_scopes=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 4.0, 'score_p50': 4.0, 'score_p95': 4.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Mostly faithful, with only minor simplifications': 1}, 'trivialization_flag_counts': {}}

### t1_solow_investment_definition

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: In the Solow model, investment per effective worker is s * A * k^alpha.
- Preambles: solow_steady_state
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=22078.6 ms, p95=22078.6 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), reasoning_presets=(none), timeout_scopes=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 1.0, 'score_p50': 1.0, 'score_p95': 1.0, 'score_ge_4_rate': 0.0, 'verdict_counts': {'Wrong, vacuous, or auto-trivialized into something like A = A.': 1}, 'trivialization_flag_counts': {'auto-trivialization': 1, 'no substantive claim': 1, 'tautology': 1}}

### t1_cobb_douglas_elasticity

- Tier: tier1_core
- Expected category: DEFINABLE
- Raw claim: For a two-factor Cobb-Douglas production function, output elasticity with respect to capital is alpha.
- Preambles: cobb_douglas_2factor
- raw_claim -> formalizer-only gate: pass@1=True, pass@3=None, pass@5=None, partial_attempts=0, partial_rate=0.0, p50=33307.7 ms, p95=33307.7 ms, failure_stages=(none), error_codes={'none': 1}, stop_reasons=(none), validation_methods={'lake_env_lean': 1}, validation_fallbacks={'lean_run_code_unavailable': 1}, repair_buckets=(none), reasoning_presets=(none), timeout_scopes=(none), semantic_alignment={'graded_attempts': 1, 'avg_score': 5.0, 'score_p50': 5.0, 'score_p95': 5.0, 'score_ge_4_rate': 1.0, 'verdict_counts': {'Faithful and non-trivial translation': 1}, 'trivialization_flag_counts': {}}
