"""
Metadata index for LeanEcon's reusable preamble modules.

The Lean source of truth lives under `lean_workspace/LeanEcon/Preamble/`.
This Python module only stores lookup metadata and reads the corresponding Lean
files from disk when prompt context or import statements are needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEAN_WORKSPACE = PROJECT_ROOT / "lean_workspace"


@dataclass(frozen=True)
class PreambleEntry:
    """A reusable LeanEcon preamble module and its discovery metadata."""

    name: str
    lean_module: str
    description: str
    keywords: tuple[str, ...]
    auto_keywords: tuple[str, ...] | None = None
    parameters: tuple[str, ...] = ()

    @property
    def lean_path(self) -> Path:
        return LEAN_WORKSPACE / Path(*self.lean_module.split(".")).with_suffix(".lean")


PREAMBLE_LIBRARY: dict[str, PreambleEntry] = {}


def _register(entry: PreambleEntry) -> None:
    PREAMBLE_LIBRARY[entry.name] = entry


_register(
    PreambleEntry(
        name="cobb_douglas_2factor",
        lean_module="LeanEcon.Preamble.Producer.CobbDouglas2Factor",
        description="Two-factor Cobb-Douglas production function with elasticity proof",
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
            "factor share",
        ),
        parameters=("A", "K", "L", "α"),
    )
)
_register(
    PreambleEntry(
        name="ces_2factor",
        lean_module="LeanEcon.Preamble.Producer.CES2Factor",
        description="Two-factor CES production function with elasticity of substitution σ",
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
    )
)
_register(
    PreambleEntry(
        name="crra_utility",
        lean_module="LeanEcon.Preamble.Consumer.CRRAUtility",
        description="CRRA utility function with derivative and RRA lemmas",
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
            "isoelastic",
            "crra utility",
            "constant relative risk aversion",
            "power utility",
        ),
        parameters=("c", "γ"),
    )
)
_register(
    PreambleEntry(
        name="cara_utility",
        lean_module="LeanEcon.Preamble.Consumer.CARAUtility",
        description="CARA utility function with derivative and ARA lemmas",
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
            "cara utility",
            "constant absolute risk aversion",
            "exponential utility",
        ),
        parameters=("c", "α"),
    )
)
_register(
    PreambleEntry(
        name="stone_geary_utility",
        lean_module="LeanEcon.Preamble.Consumer.StoneGearyUtility",
        description="Stone-Geary utility for two goods with marginal utility lemmas",
        keywords=("stone-geary", "stone geary", "les utility", "linear expenditure"),
        parameters=("x₁", "x₂", "α", "γ₁", "γ₂"),
    )
)
_register(
    PreambleEntry(
        name="price_elasticity",
        lean_module="LeanEcon.Preamble.Consumer.PriceElasticity",
        description="Price elasticity of demand as (dq/dp)·(p/q)",
        keywords=("price elasticity", "elasticity of demand", "demand elasticity"),
        parameters=("dq_dp", "p", "q"),
    )
)
_register(
    PreambleEntry(
        name="income_elasticity",
        lean_module="LeanEcon.Preamble.Consumer.IncomeElasticity",
        description="Income elasticity of demand as (dq/dm)·(m/q)",
        keywords=("income elasticity",),
        parameters=("dq_dm", "m", "q"),
    )
)
_register(
    PreambleEntry(
        name="arrow_pratt_rra",
        lean_module="LeanEcon.Preamble.Risk.ArrowPrattRRA",
        description="Arrow-Pratt measure of relative risk aversion",
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
    )
)
_register(
    PreambleEntry(
        name="arrow_pratt_ara",
        lean_module="LeanEcon.Preamble.Risk.ArrowPrattARA",
        description="Arrow-Pratt measure of absolute risk aversion",
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
    )
)
_register(
    PreambleEntry(
        name="budget_set",
        lean_module="LeanEcon.Preamble.Consumer.BudgetSet",
        description="Budget set for two goods under linear budget constraint",
        keywords=("budget set", "budget constraint", "feasible set"),
        parameters=("p₁", "p₂", "m"),
    )
)
_register(
    PreambleEntry(
        name="geometric_series",
        lean_module="LeanEcon.Preamble.Dynamic.GeometricSeries",
        description="Geometric series and its closed-form partial sum",
        keywords=("geometric series", "geometric sum", "present value"),
        parameters=("a", "r", "n"),
    )
)
_register(
    PreambleEntry(
        name="extreme_value_theorem",
        lean_module="LeanEcon.Preamble.Optimization.ExtremeValueTheorem",
        description="Extreme value theorem (Weierstrass) via Mathlib IsCompact.exists_isMaxOn",
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
        parameters=("f", "S"),
    )
)
_register(
    PreambleEntry(
        name="pareto_efficiency",
        lean_module="LeanEcon.Preamble.Welfare.ParetoEfficiency",
        description="Pareto efficiency and Pareto dominance for finite economies",
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
    )
)
_register(
    PreambleEntry(
        name="social_welfare_function",
        lean_module="LeanEcon.Preamble.Welfare.SocialWelfareFunction",
        description="Utilitarian social welfare function as weighted sum of utilities",
        keywords=(
            "social welfare function",
            "swf",
            "utilitarian",
            "welfare function",
            "weighted sum utilities",
        ),
        parameters=("n", "w", "u"),
    )
)
_register(
    PreambleEntry(
        name="marshallian_demand",
        lean_module="LeanEcon.Preamble.Consumer.MarshallianDemand",
        description="Marshallian demand functions for two-good Cobb-Douglas preferences",
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
    )
)
_register(
    PreambleEntry(
        name="indirect_utility",
        lean_module="LeanEcon.Preamble.Consumer.IndirectUtility",
        description="Indirect utility function for Cobb-Douglas preferences",
        keywords=(
            "indirect utility",
            "indirect utility function",
            "value function consumer",
            "v(p,m)",
        ),
        parameters=("α", "p₁", "p₂", "m"),
    )
)
_register(
    PreambleEntry(
        name="profit_function",
        lean_module="LeanEcon.Preamble.Producer.ProfitFunction",
        description="Profit function for a single-input firm",
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
    )
)
_register(
    PreambleEntry(
        name="cost_function",
        lean_module="LeanEcon.Preamble.Producer.CostFunction",
        description="Cost function for Cobb-Douglas technology",
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
    )
)
_register(
    PreambleEntry(
        name="bellman_equation",
        lean_module="LeanEcon.Preamble.Dynamic.BellmanEquation",
        description="Bellman equation RHS for deterministic dynamic programming",
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
        parameters=("V", "u", "f", "β"),
    )
)
_register(
    PreambleEntry(
        name="discount_factor",
        lean_module="LeanEcon.Preamble.Dynamic.DiscountFactor",
        description="Present value with geometric discounting",
        keywords=(
            "present value",
            "discount factor",
            "discounting",
            "geometric discounting",
            "net present value",
        ),
        parameters=("x", "β", "T"),
    )
)
_register(
    PreambleEntry(
        name="expected_payoff",
        lean_module="LeanEcon.Preamble.GameTheory.ExpectedPayoff",
        description="Expected payoff for 2x2 games with mixed strategies",
        keywords=(
            "expected payoff",
            "mixed strategy",
            "mixed strategies",
            "2x2 game",
            "game payoff",
            "bilinear",
        ),
        parameters=("u", "p", "q"),
    )
)
_register(
    PreambleEntry(
        name="solow_steady_state",
        lean_module="LeanEcon.Preamble.Macro.SolowSteadyState",
        description="Solow model investment and depreciation definitions",
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
        parameters=("s", "A", "n", "g", "δ", "α"),
    )
)
_register(
    PreambleEntry(
        name="phillips_curve",
        lean_module="LeanEcon.Preamble.Macro.PhillipsCurve",
        description="New Keynesian Phillips Curve with nkpc function and identity theorem",
        keywords=("phillips curve", "nkpc", "new keynesian", "inflation", "output gap"),
        parameters=("π", "β", "κ", "x"),
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
        keywords = entry.auto_keywords if auto and entry.auto_keywords else entry.keywords
        score = sum(_keyword_weight(keyword) for keyword in keywords if keyword in normalized)
        if score > 0:
            ranked.append((entry, score))
    return sorted(
        ranked,
        key=lambda item: (-item[1], item[0].name),
    )


def find_matching_preambles(claim_text: str) -> list[PreambleEntry]:
    """Return all preamble entries whose keywords match the claim text."""
    return [entry for entry, _score in rank_matching_preambles(claim_text)]


def build_preamble_block(entries: list[PreambleEntry]) -> str:
    """Concatenate raw Lean source snippets for prompt-time preamble context."""
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
    return "\n".join(f"- {entry.name}: {entry.description}" for entry in PREAMBLE_LIBRARY.values())
