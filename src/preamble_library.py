"""
Metadata index for LeanEcon's reusable preamble modules.

The Lean source of truth lives under `lean_workspace/LeanEcon/Preamble/`.
This Python module stores discovery metadata, prompt summaries, and retrieval
anchors while reading the corresponding Lean files from disk only when needed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEAN_WORKSPACE = PROJECT_ROOT / "lean_workspace"
DEFAULT_AUTO_PREAMBLE_LIMIT = int(os.environ.get("LEANECON_FORMALIZATION_AUTO_PREAMBLES", "2"))

PREAMBLE_STATUS_STRONG = "strong"
PREAMBLE_STATUS_COMPATIBILITY_ONLY = "compatibility-only"


@dataclass(frozen=True)
class PreambleEntry:
    """A reusable LeanEcon preamble module and its discovery metadata."""

    name: str
    lean_module: str
    description: str
    keywords: tuple[str, ...]
    auto_keywords: tuple[str, ...] | None = None
    parameters: tuple[str, ...] = ()
    status: str = PREAMBLE_STATUS_COMPATIBILITY_ONLY
    auto_select: bool = False
    theorem_shapes: tuple[str, ...] = ()
    candidate_imports: tuple[str, ...] = ()
    candidate_identifiers: tuple[str, ...] = ()
    retrieval_anchors: tuple[str, ...] = ()
    retrieval_notes: tuple[str, ...] = ()

    @property
    def lean_path(self) -> Path:
        return LEAN_WORKSPACE / Path(*self.lean_module.split(".")).with_suffix(".lean")

    @property
    def is_strong(self) -> bool:
        return self.status == PREAMBLE_STATUS_STRONG


@dataclass(frozen=True)
class PreambleSelectionPlan:
    """Unified preamble-selection policy shared by classify/formalize/verify."""

    explicit_preamble_names: tuple[str, ...]
    advisory_entries: tuple[PreambleEntry, ...]
    auto_entries: tuple[PreambleEntry, ...]
    selected_entries: tuple[PreambleEntry, ...]
    selection_mode: str

    @property
    def advisory_preamble_names(self) -> list[str]:
        return [entry.name for entry in self.advisory_entries]

    @property
    def auto_preamble_names(self) -> list[str]:
        return [entry.name for entry in self.auto_entries]

    @property
    def selected_preamble_names(self) -> list[str]:
        return [entry.name for entry in self.selected_entries]


PREAMBLE_LIBRARY: dict[str, PreambleEntry] = {}


def _register(entry: PreambleEntry) -> None:
    PREAMBLE_LIBRARY[entry.name] = entry


STRONG = PREAMBLE_STATUS_STRONG
COMPAT = PREAMBLE_STATUS_COMPATIBILITY_ONLY


_register(
    PreambleEntry(
        name="cobb_douglas_2factor",
        lean_module="LeanEcon.Preamble.Producer.CobbDouglas2Factor",
        description=(
            "Two-factor Cobb-Douglas production with reusable marginal-product "
            "and derivative lemmas."
        ),
        keywords=(
            "cobb-douglas",
            "cobb douglas",
            "cd production",
            "output elasticity",
            "marginal product",
            "returns to scale",
            "production function",
            "diminishing returns",
            "factor share",
            "homogeneous of degree",
        ),
        auto_keywords=(
            "cobb-douglas",
            "cobb douglas",
            "cd production",
            "output elasticity",
            "marginal product",
            "factor share",
        ),
        parameters=("A", "K", "L", "α"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`HasDerivAt (fun k => cobb_douglas A k L α) ... K`",
            "`deriv (fun k => cobb_douglas A k L α) K = ...`",
            "`α * K * K⁻¹ = α`",
        ),
        candidate_imports=("Mathlib.Analysis.Calculus.Deriv.Basic",),
        candidate_identifiers=(
            "cobb_douglas",
            "cobb_douglas_hasDerivAt_capital",
            "cobb_douglas_deriv_capital",
            "cobb_douglas_elasticity_capital",
        ),
        retrieval_anchors=(
            "cobb_douglas_hasDerivAt_capital",
            "cobb_douglas_deriv_capital",
            "Real.hasDerivAt_rpow_const",
        ),
        retrieval_notes=(
            (
                "Use the preamble derivative lemmas instead of collapsing "
                "elasticity claims to tautologies."
            ),
            (
                "Mathlib's `Real.hasDerivAt_rpow_const` needs a side "
                "condition such as `K ≠ 0 ∨ 1 ≤ α`."
            ),
        ),
    )
)
_register(
    PreambleEntry(
        name="ces_2factor",
        lean_module="LeanEcon.Preamble.Producer.CES2Factor",
        description="Definition-only CES production wrapper kept for compatibility imports.",
        keywords=(
            "ces production",
            "ces function",
            "constant elasticity of substitution",
            "returns to scale",
            "homogeneous",
            "production function",
            "elasticity of substitution",
            "homogeneous of degree",
        ),
        auto_keywords=(
            "ces production",
            "ces function",
            "constant elasticity of substitution",
            "elasticity of substitution",
        ),
        parameters=("A", "K", "L", "σ", "α"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="crra_utility",
        lean_module="LeanEcon.Preamble.Consumer.CRRAUtility",
        description=(
            "CRRA utility with Arrow-Pratt-style relative risk-aversion lemmas "
            "and a simplified benchmark identity."
        ),
        keywords=(
            "crra",
            "isoelastic",
            "crra utility",
            "constant relative risk aversion",
            "risk aversion",
            "concave utility",
            "diminishing marginal utility",
            "power utility",
            "marginal utility",
            "derivative",
        ),
        auto_keywords=(
            "crra",
            "relative risk aversion",
            "isoelastic",
            "crra utility",
            "constant relative risk aversion",
            "power utility",
        ),
        parameters=("c", "γ"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`relative_risk_aversion c u' u'' = γ` under the CRRA-style ratio condition",
            "`-c * (-γ * c⁻¹) = γ`",
        ),
        candidate_imports=(
            "Mathlib",
            "LeanEcon.Preamble.Risk.ArrowPrattRRA",
        ),
        candidate_identifiers=(
            "crra_utility",
            "crra_relative_risk_aversion_of_marginal_relation",
            "crra_rra_simplified",
            "relative_risk_aversion",
        ),
        retrieval_anchors=(
            "crra_relative_risk_aversion_of_marginal_relation",
            "relative_risk_aversion_of_second_derivative_relation",
        ),
        retrieval_notes=(
            (
                "The current strong theorem shape is Arrow-Pratt-based "
                "rather than a full derivative proof of `crra_utility`."
            ),
        ),
    )
)
_register(
    PreambleEntry(
        name="cara_utility",
        lean_module="LeanEcon.Preamble.Consumer.CARAUtility",
        description=(
            "CARA utility with Arrow-Pratt-style absolute risk-aversion lemmas "
            "and a simplified benchmark identity."
        ),
        keywords=(
            "cara",
            "cara utility",
            "constant absolute risk aversion",
            "exponential utility",
            "risk aversion",
            "exponential",
            "absolute risk",
            "marginal utility",
            "derivative",
        ),
        auto_keywords=(
            "cara",
            "cara-style",
            "cara utility",
            "absolute risk aversion",
            "constant absolute risk aversion",
            "exponential utility",
        ),
        parameters=("c", "α"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`absolute_risk_aversion u' u'' = α` under the CARA-style ratio condition",
            "`-(-α * e) / e = α`",
        ),
        candidate_imports=(
            "Mathlib",
            "LeanEcon.Preamble.Risk.ArrowPrattARA",
        ),
        candidate_identifiers=(
            "cara_utility",
            "cara_absolute_risk_aversion_of_marginal_relation",
            "cara_ara_simplified",
            "absolute_risk_aversion",
        ),
        retrieval_anchors=(
            "cara_absolute_risk_aversion_of_marginal_relation",
            "absolute_risk_aversion_of_second_derivative_relation",
        ),
        retrieval_notes=(
            (
                "The current strong theorem shape is Arrow-Pratt-based "
                "rather than a full derivative proof of `cara_utility`."
            ),
        ),
    )
)
_register(
    PreambleEntry(
        name="stone_geary_utility",
        lean_module="LeanEcon.Preamble.Consumer.StoneGearyUtility",
        description="Definition-only Stone-Geary utility wrapper kept for compatibility imports.",
        keywords=("stone-geary", "stone geary", "les utility", "linear expenditure"),
        parameters=("x₁", "x₂", "α", "γ₁", "γ₂"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="price_elasticity",
        lean_module="LeanEcon.Preamble.Consumer.PriceElasticity",
        description="Definition-only price elasticity wrapper kept for compatibility imports.",
        keywords=("price elasticity", "elasticity of demand", "demand elasticity"),
        parameters=("dq_dp", "p", "q"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="income_elasticity",
        lean_module="LeanEcon.Preamble.Consumer.IncomeElasticity",
        description="Definition-only income elasticity wrapper kept for compatibility imports.",
        keywords=("income elasticity",),
        parameters=("dq_dm", "m", "q"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="arrow_pratt_rra",
        lean_module="LeanEcon.Preamble.Risk.ArrowPrattRRA",
        description="Arrow-Pratt relative risk aversion with a reusable closed-form ratio lemma.",
        keywords=(
            "relative risk aversion",
            "rra",
            "arrow-pratt",
            "arrow pratt",
            "risk premium",
            "risk aversion coefficient",
            "concavity of utility",
        ),
        auto_keywords=(
            "relative risk aversion",
            "rra",
            "arrow-pratt",
            "arrow pratt",
            "risk aversion coefficient",
        ),
        parameters=("c", "u'", "u''"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=("`relative_risk_aversion c u' u'' = γ` from `u'' = -(γ / c) * u'`",),
        candidate_imports=("Mathlib",),
        candidate_identifiers=(
            "relative_risk_aversion",
            "relative_risk_aversion_of_second_derivative_relation",
        ),
        retrieval_anchors=("relative_risk_aversion_of_second_derivative_relation",),
        retrieval_notes=("Useful shared wrapper for CRRA-style Arrow-Pratt claims.",),
    )
)
_register(
    PreambleEntry(
        name="arrow_pratt_ara",
        lean_module="LeanEcon.Preamble.Risk.ArrowPrattARA",
        description="Arrow-Pratt absolute risk aversion with a reusable closed-form ratio lemma.",
        keywords=(
            "absolute risk aversion",
            "ara",
            "risk premium",
            "absolute risk",
            "concavity of utility",
        ),
        auto_keywords=(
            "absolute risk aversion",
            "ara",
            "absolute risk",
        ),
        parameters=("u'", "u''"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=("`absolute_risk_aversion u' u'' = α` from `u'' = -α * u'`",),
        candidate_imports=("Mathlib",),
        candidate_identifiers=(
            "absolute_risk_aversion",
            "absolute_risk_aversion_of_second_derivative_relation",
        ),
        retrieval_anchors=("absolute_risk_aversion_of_second_derivative_relation",),
        retrieval_notes=("Useful shared wrapper for CARA-style Arrow-Pratt claims.",),
    )
)
_register(
    PreambleEntry(
        name="budget_set",
        lean_module="LeanEcon.Preamble.Consumer.BudgetSet",
        description="Two-good budget-set predicate with direct membership lemmas.",
        keywords=("budget set", "budget constraint", "feasible set"),
        auto_keywords=("budget set", "budget constraint", "feasible set"),
        parameters=("p₁", "p₂", "m"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`in_budget_set p₁ p₂ m x₁ x₂`",
            "`p₁ * x₁ + p₂ * x₂ ≤ m → in_budget_set p₁ p₂ m x₁ x₂`",
        ),
        candidate_imports=("Mathlib",),
        candidate_identifiers=("in_budget_set", "budget_set_membership", "in_budget_set_iff"),
        retrieval_anchors=("budget_set_membership", "in_budget_set_iff"),
        retrieval_notes=("Prefer the named predicate over re-defining the budget set inline.",),
    )
)
_register(
    PreambleEntry(
        name="geometric_series",
        lean_module="LeanEcon.Preamble.Dynamic.GeometricSeries",
        description="Geometric partial sums with zero-horizon and one-step-recursion lemmas.",
        keywords=("geometric series", "geometric sum", "present value"),
        auto_keywords=("geometric series", "geometric sum", "present value"),
        parameters=("a", "r", "n"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`geometric_partial_sum a r 0 = 0`",
            "`geometric_partial_sum a r (n.succ) = geometric_partial_sum a r n + a * r ^ n`",
        ),
        candidate_imports=("Mathlib",),
        candidate_identifiers=(
            "geometric_partial_sum",
            "geometric_partial_sum_zero",
            "geometric_partial_sum_succ",
        ),
        retrieval_anchors=("geometric_partial_sum_succ",),
        retrieval_notes=("The recursion lemma needs the nondegeneracy assumption `r ≠ 1`.",),
    )
)
_register(
    PreambleEntry(
        name="extreme_value_theorem",
        lean_module="LeanEcon.Preamble.Optimization.ExtremeValueTheorem",
        description=(
            "Compactness wrappers for `IsMaxOn` and `IsMinOn`, including "
            "strict-concavity and strict-convexity economics-style entry points."
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
            "concave",
            "convex",
            "strictly concave",
            "strictly convex",
            "concavity",
            "convexity",
            "maximum",
            "minimum",
            "optimization",
        ),
        auto_keywords=(
            "extreme value",
            "extreme value theorem",
            "weierstrass",
            "attains maximum",
            "attains minimum",
            "compact",
            "strictly concave",
            "strictly convex",
        ),
        parameters=("f", "S"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`∃ x ∈ s, IsMaxOn f s x`",
            "`∃ x ∈ s, IsMinOn f s x`",
        ),
        candidate_imports=(
            "Mathlib.Analysis.Convex.Basic",
            "Mathlib.Topology.Order.Basic",
        ),
        candidate_identifiers=(
            "continuous_attains_max_on_compact",
            "continuous_attains_min_on_compact",
            "strictly_concave_attains_max_on_compact",
            "strictly_convex_attains_min_on_compact",
        ),
        retrieval_anchors=(
            "IsCompact.exists_isMaxOn",
            "IsCompact.exists_isMinOn",
            "strictly_concave_attains_max_on_compact",
        ),
        retrieval_notes=(
            (
                "Economics-style existence claims usually still need "
                "`IsCompact`, `Set.Nonempty`, and `ContinuousOn`."
            ),
        ),
    )
)
_register(
    PreambleEntry(
        name="pareto_efficiency",
        lean_module="LeanEcon.Preamble.Welfare.ParetoEfficiency",
        description="Definition-only Pareto-efficiency wrapper kept for compatibility imports.",
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
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="social_welfare_function",
        lean_module="LeanEcon.Preamble.Welfare.SocialWelfareFunction",
        description="Definition-only social-welfare wrapper kept for compatibility imports.",
        keywords=(
            "social welfare function",
            "swf",
            "utilitarian",
            "welfare function",
            "weighted sum utilities",
        ),
        parameters=("n", "w", "u"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="marshallian_demand",
        lean_module="LeanEcon.Preamble.Consumer.MarshallianDemand",
        description=(
            "Two-good Cobb-Douglas Marshallian demand with budget-share and "
            "budget-exhaustion lemmas."
        ),
        keywords=(
            "marshallian demand",
            "ordinary demand",
            "demand function",
            "optimal consumption",
            "utility maximization demand",
            "budget constraint",
            "tangency condition",
        ),
        auto_keywords=(
            "marshallian demand",
            "ordinary demand",
            "demand function",
            "optimal consumption",
            "utility maximization demand",
        ),
        parameters=("α", "m", "p₁", "p₂"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`p₁ * marshallian_demand_good1 α m p₁ = α * m`",
            "`p₁ * x₁ + p₂ * x₂ = m` for the two-good Cobb-Douglas demand system",
        ),
        candidate_imports=("Mathlib",),
        candidate_identifiers=(
            "marshallian_demand_good1",
            "marshallian_demand_good2",
            "marshallian_spending_good1",
            "marshallian_spending_good2",
            "marshallian_budget_exhausted",
        ),
        retrieval_anchors=(
            "marshallian_spending_good1",
            "marshallian_spending_good2",
            "marshallian_budget_exhausted",
        ),
        retrieval_notes=("Spending and budget-exhaustion lemmas need nonzero price assumptions.",),
    )
)
_register(
    PreambleEntry(
        name="indirect_utility",
        lean_module="LeanEcon.Preamble.Consumer.IndirectUtility",
        description=(
            "Cobb-Douglas indirect utility with zero-income and income-scaling lemmas."
        ),
        keywords=(
            "indirect utility",
            "indirect utility function",
            "value function consumer",
            "v(p,m)",
        ),
        auto_keywords=(
            "indirect utility",
            "indirect utility function",
            "value function consumer",
            "v(p,m)",
        ),
        parameters=("α", "p₁", "p₂", "m"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`indirect_utility_cd α p₁ p₂ 0 = 0`",
            "`indirect_utility_cd α p₁ p₂ (t * m) = t * indirect_utility_cd α p₁ p₂ m`",
        ),
        candidate_imports=("Mathlib",),
        candidate_identifiers=(
            "indirect_utility_cd",
            "indirect_utility_cd_zero_income",
            "indirect_utility_cd_income_scaling",
        ),
        retrieval_anchors=("indirect_utility_cd_income_scaling",),
        retrieval_notes=(
            (
                "The current helper theorems focus on income homogeneity "
                "rather than full duality theory."
            ),
        ),
    )
)
_register(
    PreambleEntry(
        name="profit_function",
        lean_module="LeanEcon.Preamble.Producer.ProfitFunction",
        description="Definition-only profit-function wrapper kept for compatibility imports.",
        keywords=(
            "profit function",
            "profit maximization",
            "firm profit",
            "producer surplus",
            "marginal cost",
            "marginal revenue",
            "supply function",
            "first order condition",
            "foc",
        ),
        parameters=("p", "w", "A", "α"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="cost_function",
        lean_module="LeanEcon.Preamble.Producer.CostFunction",
        description="Definition-only cost-function wrapper kept for compatibility imports.",
        keywords=(
            "cost function",
            "cost minimization",
            "conditional factor demand",
            "total cost",
            "marginal cost",
            "average cost",
            "isoquant",
            "shephard",
            "shephard's lemma",
        ),
        parameters=("w", "r", "A", "α", "q"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="bellman_equation",
        lean_module="LeanEcon.Preamble.Dynamic.BellmanEquation",
        description=(
            "Deterministic Bellman-operator scaffolding on bounded continuous "
            "functions with sup-norm contraction bounds."
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
            "recursive",
            "value function",
            "optimal control",
        ),
        auto_keywords=(
            "bellman",
            "bellman equation",
            "dynamic programming",
            "value function iteration",
            "value function",
        ),
        parameters=("V", "u", "f", "β"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`dist (bellman_operator β u f V) (bellman_operator β u f W) ≤ β * dist V W`",
            "`dist (discounted_continuation β f V) (discounted_continuation β f W) ≤ β * dist V W`",
        ),
        candidate_imports=(
            "Mathlib.Topology.ContinuousMap.Bounded.Basic",
            "Mathlib.Topology.MetricSpace.Contracting",
        ),
        candidate_identifiers=(
            "discounted_continuation",
            "bellman_operator",
            "discounted_continuation_dist_le",
            "bellman_operator_dist_le",
        ),
        retrieval_anchors=(
            "discounted_continuation_dist_le",
            "bellman_operator_dist_le",
            "BoundedContinuousFunction.dist_le_iff_of_nonempty",
        ),
        retrieval_notes=(
            "The Bellman helpers work on `BoundedContinuousFunction α ℝ` and `ContinuousMap α α`.",
            (
                "Use `contraction_mapping` for the generic fixed-point theorem "
                "when you already have `ContractingWith`."
            ),
        ),
    )
)
_register(
    PreambleEntry(
        name="contraction_mapping",
        lean_module="LeanEcon.Preamble.Dynamic.ContractionMapping",
        description=(
            "Banach fixed-point wrapper: a contracting map on a complete "
            "metric space has a unique fixed point."
        ),
        keywords=(
            "contraction mapping",
            "contracting operator",
            "fixed point",
            "banach fixed point",
            "complete metric space",
            "unique fixed point",
        ),
        auto_keywords=(
            "contraction mapping",
            "contracting operator",
            "fixed point",
            "banach fixed point",
            "complete metric space",
            "unique fixed point",
        ),
        parameters=("β", "f"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=("`ContractingWith β f → ∃! x, f x = x`",),
        candidate_imports=("Mathlib.Topology.MetricSpace.Contracting",),
        candidate_identifiers=(
            "ContractingWith",
            "contraction_has_unique_fixed_point",
            "fixedPoint",
        ),
        retrieval_anchors=(
            "contraction_has_unique_fixed_point",
            "ContractingWith.fixedPoint_unique",
            "ContractingWith.fixedPoint_isFixedPt",
        ),
        retrieval_notes=(
            "The contraction constant must live in `NNReal` / `ℝ≥0`, not plain `ℝ`.",
        ),
    )
)
_register(
    PreambleEntry(
        name="discount_factor",
        lean_module="LeanEcon.Preamble.Dynamic.DiscountFactor",
        description=(
            "Geometric-discounting helpers linked explicitly to the "
            "geometric-series preamble."
        ),
        keywords=(
            "present value",
            "discount factor",
            "discounting",
            "geometric discounting",
            "net present value",
        ),
        auto_keywords=(
            "present value",
            "discount factor",
            "discounting",
            "geometric discounting",
        ),
        parameters=("x", "β", "T"),
        status=STRONG,
        auto_select=True,
        theorem_shapes=(
            "`present_value_constant x β T = geometric_partial_sum x β T`",
            "`present_value_constant x β T.succ = present_value_constant x β T + x * β ^ T`",
        ),
        candidate_imports=("Mathlib", "LeanEcon.Preamble.Dynamic.GeometricSeries"),
        candidate_identifiers=(
            "present_value_constant",
            "present_value_constant_eq_geometric_partial_sum",
            "present_value_constant_zero_horizon",
            "present_value_constant_succ",
        ),
        retrieval_anchors=(
            "present_value_constant_eq_geometric_partial_sum",
            "present_value_constant_succ",
        ),
        retrieval_notes=(
            "The one-step recursion lemma needs the nondegeneracy assumption `β ≠ 1`.",
        ),
    )
)
_register(
    PreambleEntry(
        name="expected_payoff",
        lean_module="LeanEcon.Preamble.GameTheory.ExpectedPayoff",
        description="Definition-only expected-payoff wrapper kept for compatibility imports.",
        keywords=(
            "expected payoff",
            "mixed strategy",
            "mixed strategies",
            "2x2 game",
            "game payoff",
            "bilinear",
        ),
        parameters=("u", "p", "q"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="solow_steady_state",
        lean_module="LeanEcon.Preamble.Macro.SolowSteadyState",
        description="Definition-only Solow wrapper kept for compatibility imports.",
        keywords=(
            "solow",
            "solow model",
            "steady state",
            "steady-state",
            "solow steady state",
            "capital accumulation",
            "growth model",
            "golden rule",
            "convergence",
            "per capita",
        ),
        auto_keywords=(
            "solow",
            "solow model",
            "steady state",
            "steady-state",
            "solow steady state",
        ),
        parameters=("s", "A", "n", "g", "δ", "α"),
        status=COMPAT,
    )
)
_register(
    PreambleEntry(
        name="phillips_curve",
        lean_module="LeanEcon.Preamble.Macro.PhillipsCurve",
        description="Definition-only NKPC wrapper kept for compatibility imports.",
        keywords=("phillips curve", "nkpc", "new keynesian", "inflation", "output gap"),
        parameters=("π", "β", "κ", "x"),
        status=COMPAT,
    )
)


def _strip_lean_header(lean_code: str) -> str:
    """Drop leading import/open lines before using Lean source as prompt context."""
    lines = lean_code.splitlines()
    index = 0

    while index < len(lines) and not lines[index].strip():
        index += 1
    while index < len(lines) and lines[index].strip().startswith(("import ", "open ")):
        index += 1
    while index < len(lines) and not lines[index].strip():
        index += 1

    return "\n".join(lines[index:]).strip()


def read_preamble_source(entry: PreambleEntry, *, strip_header: bool = True) -> str:
    """Read the Lean source backing a preamble entry."""
    source = entry.lean_path.read_text(encoding="utf-8")
    return _strip_lean_header(source) if strip_header else source


def _keyword_weight(keyword: str) -> int:
    cleaned = keyword.replace("-", " ").strip()
    if " " in cleaned:
        return 3
    return 1


def rank_matching_preambles(
    claim_text: str,
    *,
    auto: bool = False,
) -> list[tuple[PreambleEntry, int]]:
    """Return preamble matches ordered by weighted keyword relevance."""
    normalized = claim_text.lower()
    ranked: list[tuple[PreambleEntry, int]] = []
    for entry in PREAMBLE_LIBRARY.values():
        if auto and not entry.auto_select:
            continue
        keywords = entry.auto_keywords if auto and entry.auto_keywords else entry.keywords
        score = sum(_keyword_weight(keyword) for keyword in keywords if keyword in normalized)
        if score > 0:
            ranked.append((entry, score))
    return sorted(ranked, key=lambda item: (-item[1], item[0].name))


def find_matching_preambles(claim_text: str) -> list[PreambleEntry]:
    """Return all preamble entries whose keywords match the claim text."""
    return [entry for entry, _score in rank_matching_preambles(claim_text)]


def select_preamble_plan(
    claim_text: str,
    *,
    explicit_preamble_names: list[str] | None = None,
    auto_limit: int = DEFAULT_AUTO_PREAMBLE_LIMIT,
) -> PreambleSelectionPlan:
    """Compute advisory, auto, and selected preambles under one shared policy."""
    explicit_names = validate_preamble_names(list(explicit_preamble_names or []))
    advisory_entries = tuple(entry for entry, _score in rank_matching_preambles(claim_text))
    bounded_auto_limit = max(0, int(auto_limit))
    auto_entries = tuple(
        entry
        for entry, _score in rank_matching_preambles(claim_text, auto=True)[:bounded_auto_limit]
    )
    selected_entries = (
        tuple(get_preamble_entries(explicit_names))
        if explicit_names
        else auto_entries
    )
    selection_mode = "explicit" if explicit_names else ("auto" if selected_entries else "none")
    return PreambleSelectionPlan(
        explicit_preamble_names=tuple(explicit_names),
        advisory_entries=advisory_entries,
        auto_entries=auto_entries,
        selected_entries=selected_entries,
        selection_mode=selection_mode,
    )


def build_preamble_block(entries: list[PreambleEntry]) -> str:
    """Concatenate raw Lean source snippets for test-time or debug inspection."""
    if not entries:
        return ""

    seen_modules: set[str] = set()
    parts: list[str] = []
    for entry in entries:
        if entry.lean_module in seen_modules:
            continue
        seen_modules.add(entry.lean_module)
        source = read_preamble_source(entry)
        if source:
            parts.append(source)
    return "\n\n".join(parts) + ("\n" if parts else "")


def serialize_preamble_entry(
    entry: PreambleEntry,
    *,
    selection_role: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable summary for API artifacts and telemetry."""
    return {
        "name": entry.name,
        "lean_module": entry.lean_module,
        "lean_path": entry.lean_path.relative_to(PROJECT_ROOT).as_posix(),
        "description": entry.description,
        "status": entry.status,
        "auto_select": entry.auto_select,
        "selection_role": selection_role,
        "parameters": list(entry.parameters),
        "theorem_shapes": list(entry.theorem_shapes),
        "candidate_imports": list(entry.candidate_imports),
        "candidate_identifiers": list(entry.candidate_identifiers),
        "retrieval_anchors": list(entry.retrieval_anchors),
        "retrieval_notes": list(entry.retrieval_notes),
    }


def build_preamble_prompt_block(entries: list[PreambleEntry]) -> str:
    """Render selected preambles as compact import-and-reference guidance."""
    if not entries:
        return ""

    seen_modules: set[str] = set()
    lines = ["SELECTED LEANECON PREAMBLES:"]
    for entry in entries:
        if entry.lean_module in seen_modules:
            continue
        seen_modules.add(entry.lean_module)
        lines.append(
            (
                f"- `{entry.name}` [{entry.status}] via "
                f"`import {entry.lean_module}`: {entry.description}"
            )
        )
        if entry.theorem_shapes:
            lines.append(f"  Theorem shapes: {' | '.join(entry.theorem_shapes[:2])}")
        if entry.candidate_identifiers:
            lines.append(
                f"  Exported identifiers: {', '.join(entry.candidate_identifiers[:4])}"
            )
        if entry.retrieval_notes:
            lines.append(f"  Notes: {' | '.join(entry.retrieval_notes[:2])}")
    return "\n".join(lines)


def build_preamble_imports(entries: list[PreambleEntry]) -> list[str]:
    """Build deduplicated Lean import statements for the selected entries."""
    imports: list[str] = []
    seen_modules: set[str] = set()
    for entry in entries:
        if entry.lean_module in seen_modules:
            continue
        seen_modules.add(entry.lean_module)
        imports.append(f"import {entry.lean_module}")
    return imports


def normalize_preamble_names(names: list[str]) -> list[str]:
    """Trim and deduplicate preamble names while preserving order."""
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_name in names:
        cleaned = raw_name.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def unknown_preamble_names(names: list[str]) -> list[str]:
    """Return any explicit preamble names that are not in the catalog."""
    normalized = normalize_preamble_names(names)
    return [name for name in normalized if name not in PREAMBLE_LIBRARY]


def validate_preamble_names(names: list[str]) -> list[str]:
    """Return normalized names or raise when an explicit preamble is unknown."""
    normalized = normalize_preamble_names(names)
    unknown = unknown_preamble_names(normalized)
    if unknown:
        joined = ", ".join(unknown)
        raise ValueError(f"Unknown preamble_names: {joined}")
    return normalized


def get_preamble_entries(names: list[str]) -> list[PreambleEntry]:
    """Look up preamble entries by name. Silently skips unknown names."""
    entries: list[PreambleEntry] = []
    seen_names: set[str] = set()
    for name in names:
        if name in seen_names:
            continue
        entry = PREAMBLE_LIBRARY.get(name)
        if entry is None:
            continue
        entries.append(entry)
        seen_names.add(name)
    return entries


def build_preamble_catalog_summary() -> str:
    """Compact text listing of all preamble modules for LLM context."""
    lines: list[str] = []
    for entry in PREAMBLE_LIBRARY.values():
        qualifier = "auto-select" if entry.auto_select else "explicit-only"
        summary = f"- {entry.name} [{entry.status}, {qualifier}]: {entry.description}"
        if entry.theorem_shapes:
            summary += f" Shapes: {' | '.join(entry.theorem_shapes[:1])}."
        lines.append(summary)
    return "\n".join(lines)
