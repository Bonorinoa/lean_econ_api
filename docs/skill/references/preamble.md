# LeanEcon preamble catalog

These are the 29 reusable economic definitions available in LeanEcon. Pass these names in `preamble_names` when calling `POST /api/v1/formalize`.

The classifier's `preamble_matches` field automatically suggests relevant preambles based on keyword matching.

After formalization, `POST /api/v1/verify` queues an asynchronous job and
returns `202 + job_id`. Track completion with either
`GET /api/v1/jobs/{job_id}` or `GET /api/v1/jobs/{job_id}/stream`.

## Consumer theory

| Name | Description | Parameters |
|---|---|---|
| `crra_utility` | CRRA (isoelastic) utility function | c, γ |
| `cara_utility` | CARA (exponential) utility function | c, α |
| `stone_geary_utility` | Stone-Geary / linear expenditure system utility | x₁, x₂, α, γ₁, γ₂ |
| `budget_set` | Budget set for two goods | p₁, p₂, m |
| `price_elasticity` | Price elasticity of demand (dq/dp)·(p/q) | dq_dp, p, q |
| `income_elasticity` | Income elasticity of demand (dq/dm)·(m/q) | dq_dm, m, q |
| `marshallian_demand` | Marshallian demand for Cobb-Douglas | α, m, p₁, p₂ |
| `indirect_utility` | Indirect utility for Cobb-Douglas | α, p₁, p₂, m |
| `slutsky_equation` | Slutsky equation template | xᵢ, pⱼ, hᵢ, m |

## Producer theory

| Name | Description | Parameters |
|---|---|---|
| `cobb_douglas_2factor` | Two-factor Cobb-Douglas f(K,L) = A·K^α·L^(1-α) | A, K, L, α |
| `ces_2factor` | Two-factor CES production function | A, K, L, σ, α |
| `cost_function` | Cost function for Cobb-Douglas technology | w, r, A, α, q |
| `profit_function` | Profit function for single-input firm | p, w, A, α |

## Risk

| Name | Description | Parameters |
|---|---|---|
| `arrow_pratt_rra` | Relative risk aversion -c·u''/u' | c, u', u'' |
| `arrow_pratt_ara` | Absolute risk aversion -u''/u' | u', u'' |

## Dynamic optimization

| Name | Description | Parameters |
|---|---|---|
| `bellman_equation` | Bellman equation for deterministic DP | V, u, f, β |
| `euler_equation` | Euler equation for intertemporal consumption | β, r, γ, c |
| `discount_factor` | Present value with geometric discounting | x, β, T |
| `geometric_series` | Geometric series partial sum | a, r, n |

## Optimization

| Name | Description | Parameters |
|---|---|---|
| `contraction_mapping` | Contraction mapping / Banach fixed point | T, β |
| `blackwell_sufficient` | Blackwell's sufficient conditions | T, β |
| `extreme_value_theorem` | Weierstrass extreme value theorem | f, S |
| `envelope_theorem` | Envelope theorem for value derivatives | V, θ, λ |
| `implicit_function_condition` | Implicit function theorem for comparative statics | F, x, θ |

## Welfare

| Name | Description | Parameters |
|---|---|---|
| `pareto_efficiency` | Pareto efficiency and dominance | n, u, X |
| `social_welfare_function` | Utilitarian SWF as weighted sum | n, w, u |

## Game theory

| Name | Description | Parameters |
|---|---|---|
| `expected_payoff` | Expected payoff for 2x2 mixed-strategy games | u, p, q |

## Macroeconomics

| Name | Description | Parameters |
|---|---|---|
| `solow_steady_state` | Solow model steady-state condition | s, A, n, g, δ, α |
| `phillips_curve` | New Keynesian Phillips Curve | π, β, κ, x |

## Usage examples

**CRRA verification with preamble:**
```
1. POST /api/v1/classify { "raw_claim": "Under CRRA utility, RRA equals gamma" }
   → category: "DEFINABLE", preamble_matches: ["crra_utility", "arrow_pratt_rra"]

2. POST /api/v1/formalize { "raw_claim": "...", "preamble_names": ["crra_utility"] }
   → theorem_code with CRRA definition imported

3. POST /api/v1/verify { "theorem_code": "..." }
   → { "job_id": "...", "status": "queued" }
```

**Cobb-Douglas with preamble:**
```
1. POST /api/v1/classify { "raw_claim": "Cobb-Douglas output elasticity equals alpha" }
   → category: "DEFINABLE", preamble_matches: ["cobb_douglas_2factor"]

2. POST /api/v1/formalize { "raw_claim": "...", "preamble_names": ["cobb_douglas_2factor"] }
   → theorem_code ready for async verify
```

**Simple algebraic claim (no preamble needed):**
```
1. POST /api/v1/classify { "raw_claim": "The sum of two even numbers is even" }
   → category: "ALGEBRAIC", preamble_matches: []

2. POST /api/v1/formalize { "raw_claim": "..." }
   → No preamble_names needed
```
