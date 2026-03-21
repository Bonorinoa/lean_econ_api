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


# --- Production functions ---

_register(PreambleEntry(
    name="cobb_douglas_2factor",
    lean_code="""\
/-- Two-factor Cobb-Douglas production function. -/
noncomputable def cobb_douglas (A K L α : ℝ) : ℝ := A * K ^ α * L ^ (1 - α)""",
    description="Two-factor Cobb-Douglas production function f(K,L) = A·K^α·L^(1-α)",
    keywords=("cobb-douglas", "cobb douglas", "cd production"),
    parameters=("A", "K", "L", "α"),
))

_register(PreambleEntry(
    name="ces_2factor",
    lean_code="""\
/-- Two-factor CES production function. -/
noncomputable def ces_production (A K L σ α : ℝ) : ℝ :=
  A * (α * K ^ ((σ - 1) / σ) + (1 - α) * L ^ ((σ - 1) / σ)) ^ (σ / (σ - 1))""",
    description="Two-factor CES production function with elasticity of substitution σ",
    keywords=("ces production", "ces function", "constant elasticity of substitution"),
    parameters=("A", "K", "L", "σ", "α"),
))

# --- Utility functions ---

_register(PreambleEntry(
    name="crra_utility",
    lean_code="""\
/-- CRRA (isoelastic) utility function.
    u(c) = c^(1-γ)/(1-γ) for γ ≠ 1; log(c) for γ = 1. -/
noncomputable def crra_utility (c γ : ℝ) : ℝ := c ^ (1 - γ) / (1 - γ)""",
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

# --- Demand / Elasticity ---

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

# --- Risk measures ---

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

# --- Budget / Constraints ---

_register(PreambleEntry(
    name="budget_set",
    lean_code="""\
/-- Budget set for two goods: {(x₁, x₂) | p₁·x₁ + p₂·x₂ ≤ m}. -/
def in_budget_set (p₁ p₂ m x₁ x₂ : ℝ) : Prop := p₁ * x₁ + p₂ * x₂ ≤ m""",
    description="Budget set for two goods under linear budget constraint",
    keywords=("budget set", "budget constraint", "feasible set"),
    parameters=("p₁", "p₂", "m"),
))

# --- Sequences / Convergence ---

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
