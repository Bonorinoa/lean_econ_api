"""
Static library of common economic definitions in Lean 4.

Think of this preamble as econlib_mini, our first public effort to advance
the coverage of economic theory in formal systems such as Lean 4. Each entry
maps a concept name to:

  - lean_code: importable Lean 4 definition (compiles with Mathlib)
  - description: plain English for the explainer
  - keywords: trigger words for matching against user claims
  - parameters: what the user might need to specify

These definitions are prepended to the formalization before the theorem
statement. They must be sorry-free and compile with `import Mathlib`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreambleEntry:
    """A reusable Lean 4 definition for economic formalization."""

    name: str
    lean_code: str
    description: str
    keywords: tuple[str, ...]
    parameters: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# The library
# ---------------------------------------------------------------------------

PREAMBLE_LIBRARY: dict[str, PreambleEntry] = {}


def _register(entry: PreambleEntry) -> None:
    PREAMBLE_LIBRARY[entry.name] = entry


# ---------------------------------------------------------------------------
# Production functions
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="cobb_douglas_2factor",
    lean_code="""\
/-- Two-factor Cobb-Douglas production function. -/
noncomputable def cobb_douglas (A K L α : ℝ) : ℝ :=
  A * Real.rpow K α * Real.rpow L (1 - α)""",
    description="Two-factor Cobb-Douglas production function f(K,L) = A·K^α·L^(1-α)",
    keywords=(
        "cobb-douglas",
        "cobb douglas",
        "cd production",
        "output elasticity",
    ),
    parameters=("A", "K", "L", "α"),
))

_register(PreambleEntry(
    name="ces_2factor",
    lean_code="""\
/-- Two-factor CES production function. -/
noncomputable def ces_production (A K L σ α : ℝ) : ℝ :=
  A * Real.rpow
    (α * Real.rpow K ((σ - 1) / σ) + (1 - α) * Real.rpow L ((σ - 1) / σ))
    (σ / (σ - 1))""",
    description="Two-factor CES production function with elasticity of substitution σ",
    keywords=("ces production", "ces function", "constant elasticity of substitution"),
    parameters=("A", "K", "L", "σ", "α"),
))


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="crra_utility",
    lean_code="""\
/-- CRRA (isoelastic) utility function.
    u(c) = c^(1-γ)/(1-γ) for γ ≠ 1; log(c) for γ = 1. -/
noncomputable def crra_utility (c γ : ℝ) : ℝ :=
  Real.rpow c (1 - γ) / (1 - γ)""",
    description="CRRA (constant relative risk aversion) utility function",
    keywords=("crra", "isoelastic", "crra utility", "constant relative risk aversion"),
    parameters=("c", "γ"),
))

_register(PreambleEntry(
    name="cara_utility",
    lean_code="""\
/-- CARA (negative exponential) utility function.
    u(c) = -exp(-α·c) / α for α > 0. -/
noncomputable def cara_utility (c α : ℝ) : ℝ := -(Real.exp (-α * c)) / α""",
    description="CARA (constant absolute risk aversion) utility function",
    keywords=("cara", "cara utility", "constant absolute risk aversion", "exponential utility"),
    parameters=("c", "α"),
))

_register(PreambleEntry(
    name="stone_geary_utility",
    lean_code="""\
/-- Stone-Geary (translated log) utility for two goods.
    u(x₁, x₂) = α·log(x₁ - γ₁) + (1-α)·log(x₂ - γ₂) -/
noncomputable def stone_geary_utility (x₁ x₂ α γ₁ γ₂ : ℝ) : ℝ :=
  α * Real.log (x₁ - γ₁) + (1 - α) * Real.log (x₂ - γ₂)""",
    description="Stone-Geary (linear expenditure system) utility for two goods",
    keywords=("stone-geary", "stone geary", "les utility", "linear expenditure"),
    parameters=("x₁", "x₂", "α", "γ₁", "γ₂"),
))


# ---------------------------------------------------------------------------
# Demand / elasticity
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="price_elasticity",
    lean_code="""\
/-- Price elasticity of demand: (dq/dp) · (p/q). -/
noncomputable def price_elasticity (dq_dp p q : ℝ) : ℝ := dq_dp * (p / q)""",
    description="Price elasticity of demand as (dq/dp)·(p/q)",
    keywords=("price elasticity", "elasticity of demand", "demand elasticity"),
    parameters=("dq_dp", "p", "q"),
))

_register(PreambleEntry(
    name="income_elasticity",
    lean_code="""\
/-- Income elasticity of demand: (dq/dm) · (m/q). -/
noncomputable def income_elasticity (dq_dm m q : ℝ) : ℝ := dq_dm * (m / q)""",
    description="Income elasticity of demand as (dq/dm)·(m/q)",
    keywords=("income elasticity",),
    parameters=("dq_dm", "m", "q"),
))


# ---------------------------------------------------------------------------
# Risk measures
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="arrow_pratt_rra",
    lean_code="""\
/-- Arrow-Pratt coefficient of relative risk aversion: -c·u''(c)/u'(c). -/
noncomputable def relative_risk_aversion (c u' u'' : ℝ) : ℝ := -(c * u'') / u'""",
    description="Arrow-Pratt measure of relative risk aversion",
    keywords=("relative risk aversion", "rra", "arrow-pratt", "arrow pratt"),
    parameters=("c", "u'", "u''"),
))

_register(PreambleEntry(
    name="arrow_pratt_ara",
    lean_code="""\
/-- Arrow-Pratt coefficient of absolute risk aversion: -u''(c)/u'(c). -/
noncomputable def absolute_risk_aversion (u' u'' : ℝ) : ℝ := -(u'') / u'""",
    description="Arrow-Pratt measure of absolute risk aversion",
    keywords=("absolute risk aversion", "ara"),
    parameters=("u'", "u''"),
))


# ---------------------------------------------------------------------------
# Budget / constraints
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="budget_set",
    lean_code="""\
/-- Budget set for two goods: {(x₁, x₂) | p₁·x₁ + p₂·x₂ ≤ m}. -/
def in_budget_set (p₁ p₂ m x₁ x₂ : ℝ) : Prop := p₁ * x₁ + p₂ * x₂ ≤ m""",
    description="Budget set for two goods under linear budget constraint",
    keywords=("budget set", "budget constraint", "feasible set"),
    parameters=("p₁", "p₂", "m"),
))


# ---------------------------------------------------------------------------
# Sequences / convergence
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="geometric_series",
    lean_code="""\
/-- Geometric series partial sum: Σ_{i=0}^{n-1} a·r^i = a·(1-r^n)/(1-r). -/
-- Note: Mathlib has `Finset.geom_sum_eq` for this identity.
noncomputable def geometric_partial_sum (a r : ℝ) (n : ℕ) : ℝ :=
  a * (1 - r ^ n) / (1 - r)""",
    description="Geometric series and its closed-form partial sum",
    keywords=("geometric series", "geometric sum", "present value"),
    parameters=("a", "r", "n"),
))


# ---------------------------------------------------------------------------
# Optimization & fixed points
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="contraction_mapping",
    lean_code="""\
/- A function T on a metric space is a contraction if there exists β ∈ [0,1)
    such that d(Tx, Ty) ≤ β · d(x,y) for all x, y. -/
-- Note: Mathlib provides `ContractingWith` in `Mathlib.Topology.MetricSpace.Contracting`.
-- Use `ContractingWith β T` directly in theorem statements.
-- The Banach fixed point theorem is `ContractingWith.fixedPoint_unique`. """,
    description=(
        "Contraction mapping / Banach fixed point theorem. "
        "Mathlib provides ContractingWith β T and the fixed point uniqueness theorem."
    ),
    keywords=(
        "contraction mapping",
        "contraction",
        "banach fixed point",
        "fixed point",
        "bellman operator",
        "contraction operator",
    ),
    parameters=("T", "β"),
))

_register(PreambleEntry(
    name="blackwell_sufficient",
    lean_code="""\
/- Blackwell's sufficient conditions for a contraction.
    An operator T is a contraction if it satisfies:
    (1) Monotonicity: f ≤ g → Tf ≤ Tg
    (2) Discounting: T(f + a) ≤ Tf + β·a for some β ∈ [0,1)

    When stated for value functions V : S → ℝ, these conditions are
    typically checked algebraically after substituting the Bellman equation.
    The contraction property then follows from Blackwell (1965). -/
-- This is a proof template, not a Lean definition. The typical workflow:
-- 1. Define the operator T
-- 2. Prove monotonicity as an algebraic claim
-- 3. Prove discounting as an algebraic claim
-- 4. Conclude T is a contraction (use ContractingWith from Mathlib)""",
    description=(
        "Blackwell's sufficient conditions for a contraction: monotonicity + discounting. "
        "Reduces contraction verification to two algebraic checks."
    ),
    keywords=(
        "blackwell",
        "blackwell sufficient",
        "blackwell conditions",
        "monotonicity and discounting",
        "sufficient conditions contraction",
    ),
    parameters=("T", "β"),
))

_register(PreambleEntry(
    name="extreme_value_theorem",
    lean_code="""\
/- The extreme value theorem: a continuous function on a compact set attains
    its maximum and minimum.
    Mathlib provides this as `IsCompact.exists_isMaxOn` and
    `IsCompact.exists_isMinOn` in `Mathlib.Topology.Order.Basic`. -/
-- Use directly in theorem statements:
-- `IsCompact S → ContinuousOn f S → ∃ x ∈ S, IsMaxOn f S x`""",
    description=(
        "Extreme value theorem (Weierstrass). Continuous functions on compact sets "
        "attain their bounds. Available in Mathlib."
    ),
    keywords=(
        "extreme value",
        "extreme value theorem",
        "weierstrass",
        "maximum theorem",
        "attains maximum",
        "attains minimum",
        "compact",
        "continuous maximum",
        "berge",
    ),
    parameters=("f", "S"),
))


# ---------------------------------------------------------------------------
# Welfare economics
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="pareto_efficiency",
    lean_code="""\
/-- An allocation x is Pareto efficient if no other feasible allocation
    makes everyone weakly better off and someone strictly better off.

    For a finite economy with n agents and utility functions uᵢ : X → ℝ,
    we define Pareto dominance as a predicate on allocation pairs. -/
def pareto_dominates {n : ℕ} {X : Type*}
    (u : Fin n → X → ℝ) (x y : X) : Prop :=
  (∀ i, u i x ≤ u i y) ∧ (∃ i, u i x < u i y)

def pareto_efficient {n : ℕ} {X : Type*}
    (u : Fin n → X → ℝ) (feasible : Set X) (x : X) : Prop :=
  x ∈ feasible ∧ ∀ y, y ∈ feasible → ¬pareto_dominates u x y""",
    description=(
        "Pareto efficiency and Pareto dominance for finite economies. "
        "Defines dominance as a predicate on allocation pairs."
    ),
    keywords=(
        "pareto",
        "pareto efficient",
        "pareto optimal",
        "pareto dominance",
        "welfare",
        "efficiency",
        "first welfare",
        "second welfare",
    ),
    parameters=("n", "u", "X"),
))

_register(PreambleEntry(
    name="social_welfare_function",
    lean_code="""\
/-- A utilitarian social welfare function: weighted sum of utilities. -/
noncomputable def utilitarian_swf {n : ℕ} {X : Type*}
    (w : Fin n → ℝ) (u : Fin n → X → ℝ) (x : X) : ℝ :=
  Finset.univ.sum fun i => w i * u i x""",
    description="Utilitarian social welfare function as weighted sum of utilities.",
    keywords=(
        "social welfare function",
        "swf",
        "utilitarian",
        "welfare function",
        "weighted sum utilities",
    ),
    parameters=("n", "w", "u"),
))


# ---------------------------------------------------------------------------
# Comparative statics & monotonicity
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="implicit_function_condition",
    lean_code="""\
/- Implicit function theorem condition: if F(x,θ) = 0 and ∂F/∂x ≠ 0,
    then dx/dθ = -(∂F/∂θ)/(∂F/∂x).

    For comparative statics, state this as the algebraic identity after
    computing the partial derivatives. -/
-- Example usage for a first-order condition F(x,θ) = 0:
-- theorem comparative_static (Fx Fθ : ℝ) (hFx : Fx ≠ 0) :
--     -(Fθ / Fx) = -(Fθ * Fx⁻¹) := by field_simp""",
    description=(
        "Implicit function theorem for comparative statics. "
        "Reduces to dx/dθ = -(∂F/∂θ)/(∂F/∂x) as an algebraic identity."
    ),
    keywords=(
        "implicit function",
        "comparative statics",
        "comparative static",
        "dx/dtheta",
        "implicit differentiation",
    ),
    parameters=("F", "x", "θ"),
))

_register(PreambleEntry(
    name="envelope_theorem",
    lean_code="""\
/- Envelope theorem: for V(θ) = max_x f(x,θ) s.t. g(x,θ) ≤ 0,
    dV/dθ = ∂L/∂θ evaluated at the optimum, where L is the Lagrangian.

    In practice, state the derivative identity algebraically. -/
-- Example: indirect utility V(p,m) satisfies ∂V/∂m = λ (Roy's identity setup)
-- theorem envelope (df_dtheta lambda dg_dtheta : ℝ) :
--     df_dtheta - lambda * dg_dtheta = df_dtheta - lambda * dg_dtheta := by ring""",
    description=(
        "Envelope theorem: dV/dθ = ∂L/∂θ at the optimum. "
        "State the derivative identity algebraically after substitution."
    ),
    keywords=(
        "envelope theorem",
        "envelope",
        "dv/dtheta",
        "indirect utility derivative",
        "roy's identity",
        "shephard's lemma",
        "hotelling's lemma",
    ),
    parameters=("V", "θ", "λ"),
))


# ---------------------------------------------------------------------------
# Consumer theory
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="slutsky_equation",
    lean_code="""\
/- Slutsky equation: the total effect of a price change on demand
    decomposes into substitution and income effects.

    ∂xᵢ/∂pⱼ = ∂hᵢ/∂pⱼ - xⱼ · ∂xᵢ/∂m

    where hᵢ is Hicksian demand and xᵢ is Marshallian demand.
    State this as an algebraic identity after computing the derivatives. -/
-- Typical formalization: given the three derivative values as hypotheses,
-- prove their relationship.
-- theorem slutsky (dx_dp dh_dp x_j dx_dm : ℝ)
--     (hslutsky : dx_dp = dh_dp - x_j * dx_dm) :
--     dx_dp = dh_dp - x_j * dx_dm := by exact hslutsky""",
    description=(
        "Slutsky equation: decomposition of price effect into substitution "
        "and income effects."
    ),
    keywords=(
        "slutsky",
        "slutsky equation",
        "substitution effect",
        "income effect",
        "hicksian demand",
        "compensated demand",
    ),
    parameters=("xᵢ", "pⱼ", "hᵢ", "m"),
))

_register(PreambleEntry(
    name="marshallian_demand",
    lean_code="""\
/-- Marshallian (ordinary) demand for a two-good Cobb-Douglas economy:
    x₁*(p₁, p₂, m) = α·m/p₁ and x₂*(p₁, p₂, m) = (1-α)·m/p₂. -/
noncomputable def marshallian_demand_good1 (α m p₁ : ℝ) : ℝ := α * m / p₁
noncomputable def marshallian_demand_good2 (α m p₂ : ℝ) : ℝ := (1 - α) * m / p₂""",
    description="Marshallian demand functions for two-good Cobb-Douglas preferences.",
    keywords=(
        "marshallian demand",
        "ordinary demand",
        "demand function",
        "optimal consumption",
        "utility maximization demand",
    ),
    parameters=("α", "m", "p₁", "p₂"),
))

_register(PreambleEntry(
    name="indirect_utility",
    lean_code="""\
/-- Indirect utility for Cobb-Douglas preferences:
    V(p₁, p₂, m) = (α/p₁)^α · ((1-α)/p₂)^(1-α) · m -/
noncomputable def indirect_utility_cd (α p₁ p₂ m : ℝ) : ℝ :=
  Real.rpow (α / p₁) α * Real.rpow ((1 - α) / p₂) (1 - α) * m""",
    description="Indirect utility function for Cobb-Douglas preferences.",
    keywords=(
        "indirect utility",
        "indirect utility function",
        "value function consumer",
        "v(p,m)",
    ),
    parameters=("α", "p₁", "p₂", "m"),
))


# ---------------------------------------------------------------------------
# Producer theory
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="profit_function",
    lean_code="""\
/-- Profit function: π(p,w) = p·f(x*(w,p)) - w·x*(w,p)
    For Cobb-Douglas f(x) = A·x^α, the profit function reduces to an
    algebraic expression after substituting the optimal input choice. -/
noncomputable def profit (p w A α : ℝ) (x_star : ℝ) : ℝ :=
  p * (A * Real.rpow x_star α) - w * x_star""",
    description="Profit function for a single-input firm.",
    keywords=(
        "profit function",
        "profit maximization",
        "firm profit",
        "producer surplus",
    ),
    parameters=("p", "w", "A", "α"),
))

_register(PreambleEntry(
    name="cost_function",
    lean_code="""\
/-- Cost function for a Cobb-Douglas technology f(K,L) = A·K^α·L^(1-α):
    C(w,r,q) = q · (w/(1-α))^(1-α) · (r/α)^α / A -/
noncomputable def cost_cd (w r A α q : ℝ) : ℝ :=
  q * Real.rpow (w / (1 - α)) (1 - α) * Real.rpow (r / α) α / A""",
    description="Cost function for Cobb-Douglas technology.",
    keywords=(
        "cost function",
        "cost minimization",
        "conditional factor demand",
        "total cost",
    ),
    parameters=("w", "r", "A", "α", "q"),
))


# ---------------------------------------------------------------------------
# Dynamic programming / macro
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="bellman_equation",
    lean_code="""\
/- Bellman equation for a deterministic infinite-horizon problem:
    V(k) = max_{k'} { u(f(k) - k') + β·V(k') }

    After substituting the Euler equation at the optimum, claims about
    the value function typically reduce to algebraic identities. -/
-- Typical workflow:
-- 1. Define u, f, β as parameters
-- 2. State the Euler equation: u'(c) = β·f'(k')·u'(c')
-- 3. After substitution, prove the resulting algebraic identity""",
    description=(
        "Bellman equation for deterministic dynamic programming. "
        "Claims reduce to algebraic identities after Euler equation substitution."
    ),
    keywords=(
        "bellman",
        "bellman equation",
        "dynamic programming",
        "value function iteration",
        "euler equation",
        "optimal savings",
        "ramsey",
        "cake eating",
    ),
    parameters=("V", "u", "f", "β"),
))

_register(PreambleEntry(
    name="euler_equation",
    lean_code="""\
/- Euler equation (consumption): u'(cₜ) = β·(1+r)·u'(cₜ₊₁).
    For CRRA utility u(c) = c^(1-γ)/(1-γ), this becomes:
    cₜ^(-γ) = β·(1+r)·cₜ₊₁^(-γ)

    After taking ratios and simplifying, the consumption growth rate is:
    cₜ₊₁/cₜ = (β·(1+r))^(1/γ) -/
-- State the simplified ratio as the algebraic claim to verify.""",
    description=(
        "Euler equation for intertemporal consumption. "
        "CRRA version gives consumption growth rate."
    ),
    keywords=(
        "euler equation",
        "consumption euler",
        "euler equation consumption",
        "intertemporal",
        "consumption growth",
        "savings decision",
    ),
    parameters=("β", "r", "γ", "c"),
))

_register(PreambleEntry(
    name="discount_factor",
    lean_code="""\
/-- Present value with geometric discounting:
    PV = Σ_{t=0}^{T-1} β^t · xₜ
    For constant x, PV = x · (1 - β^T) / (1 - β). -/
noncomputable def present_value_constant (x β : ℝ) (T : ℕ) : ℝ :=
  x * (1 - β ^ T) / (1 - β)""",
    description="Present value with geometric discounting.",
    keywords=(
        "present value",
        "discount factor",
        "discounting",
        "geometric discounting",
        "net present value",
    ),
    parameters=("x", "β", "T"),
))


# ---------------------------------------------------------------------------
# Game theory
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="expected_payoff",
    lean_code="""\
/-- Expected payoff in a finite game: Σᵢ pᵢ · uᵢ
    For mixed strategies in 2-player games, this is the bilinear form. -/
noncomputable def expected_payoff_2x2
    (u₁₁ u₁₂ u₂₁ u₂₂ p q : ℝ) : ℝ :=
  p * q * u₁₁ + p * (1 - q) * u₁₂ +
  (1 - p) * q * u₂₁ + (1 - p) * (1 - q) * u₂₂""",
    description=(
        "Expected payoff for 2x2 games with mixed strategies. "
        "Nash equilibrium conditions reduce to algebraic first-order conditions."
    ),
    keywords=(
        "expected payoff",
        "mixed strategy",
        "mixed strategies",
        "2x2 game",
        "game payoff",
        "bilinear",
    ),
    parameters=("u", "p", "q"),
))


# ---------------------------------------------------------------------------
# Macroeconomics
# ---------------------------------------------------------------------------

_register(PreambleEntry(
    name="solow_steady_state",
    lean_code="""\
/- Solow model steady-state capital per effective worker:
    k* = (s·A / (n + g + δ))^(1/(1-α))

    The steady-state condition s·f(k) = (n+g+δ)·k with f(k) = A·k^α
    can be restated algebraically after substitution. -/
-- Typical claim: at steady state, s·A·k^α = (n+g+δ)·k
-- After dividing by k: s·A·k^(α-1) = n+g+δ
-- Formalize as the algebraic identity at steady state.""",
    description=(
        "Solow model steady-state condition. "
        "Claims reduce to algebraic identities after substituting f(k) = Ak^α."
    ),
    keywords=(
        "solow",
        "solow model",
        "steady state",
        "steady-state",
        "solow steady state",
        "capital accumulation",
        "growth model",
    ),
    parameters=("s", "A", "n", "g", "δ", "α"),
))

_register(PreambleEntry(
    name="phillips_curve",
    lean_code="""\
/- New Keynesian Phillips Curve (linearized):
    πₜ = β·E[πₜ₊₁] + κ·xₜ
    where π is inflation, x is output gap, β is discount factor, κ is slope. -/
-- For verification purposes, this is typically stated as the algebraic
-- relationship between the variables, with expectations resolved.""",
    description=(
        "New Keynesian Phillips Curve. Linear relationship between "
        "inflation, expected inflation, and output gap."
    ),
    keywords=(
        "phillips curve",
        "nkpc",
        "new keynesian",
        "inflation",
        "output gap",
    ),
    parameters=("π", "β", "κ", "x"),
))


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def find_matching_preambles(claim_text: str) -> list[PreambleEntry]:
    """Return all preamble entries whose keywords match the claim text."""
    normalized = claim_text.lower()
    matches = []
    for entry in PREAMBLE_LIBRARY.values():
        if any(kw in normalized for kw in entry.keywords):
            matches.append(entry)
    return matches


def build_preamble_block(entries: list[PreambleEntry]) -> str:
    """Concatenate Lean definitions into a single preamble block."""
    if not entries:
        return ""
    parts = [entry.lean_code.strip() for entry in entries]
    return "\n\n".join(parts) + "\n"


def get_preamble_entries(names: list[str]) -> list[PreambleEntry]:
    """Look up preamble entries by name. Silently skips unknown names."""
    entries = []
    for name in names:
        if name in PREAMBLE_LIBRARY:
            entries.append(PREAMBLE_LIBRARY[name])
    return entries
