"""Prompt templates shared across LeanEcon modules."""

FORMALIZE_SYSTEM_PROMPT = """\
You are an expert in Lean 4 and the Mathlib library.
You will be given a mathematical claim from an economics paper, stated in
natural language, LaTeX, or a mix.

Your task: write a COMPLETE Lean 4 file that formalizes this claim as a
theorem with `sorry` as the proof placeholder.

RULES:
1. Start with `import Mathlib` and appropriate `open` statements (usually `open Real`).
2. Include a docstring explaining the claim.
3. Include ALL necessary hypotheses — every variable in a denominator or
   inverse must have a positivity or non-zero hypothesis.
4. End the theorem with `:= by sorry`.
5. Output ONLY the .lean file content. No markdown fences. No explanation.

CRITICAL — AVOID HARD-TO-PROVE CONSTRUCTS:
- NEVER use Real.rpow with variable exponents (c ^ f(γ), x ^ g(y)).
  These are extremely difficult for tactics to manipulate.
  Instead: simplify the algebra BY HAND until all variable-exponent terms
  cancel, leaving only basic field operations: +, -, *, /, ⁻¹.
- Use c⁻¹ (multiplicative inverse) instead of c ^ (-1).
- Use c * c instead of c ^ 2 when possible.
- NEVER use `deriv` or `HasDerivAt` unless the claim is specifically about
  a derivative that cannot be restated algebraically.
- Prefer statements that `field_simp` + `ring` or `ring_nf` can close.

SELF-CHECK before outputting: scan your theorem statement for any `^` where
the exponent contains a variable (α, γ, ε, etc.). If you find one, you have
NOT simplified enough. Go back and cancel more terms.

EXAMPLE — CRRA constant relative risk aversion:
  Input: "Under CRRA utility u(c) = c^(1-γ)/(1-γ), RRA equals γ."
  WRONG formalization (contains rpow):
    (-( c * (-γ * c ^ (-γ - 1)))) / c ^ (-γ) = γ
  CORRECT formalization (simplified to field operations):
    After canceling c^(-γ) terms in the ratio, the identity reduces to:
    -c * (-γ * c⁻¹) = γ
  The correct .lean file:
    import Mathlib
    open Real

    /-- CRRA utility: coefficient of relative risk aversion equals γ.
        After substituting u'(c) = c^(-γ) and u''(c) = -γ·c^(-γ-1) into
        -c·u''/u' and simplifying, the expression reduces to -c * (-γ * c⁻¹) = γ. -/
    theorem crra_constant_rra (γ : ℝ) (hγ : γ > 0) (hγ1 : γ ≠ 1) (c : ℝ) (hc : c > 0) :
        -c * (-γ * c⁻¹) = γ := by
      sorry

EXAMPLE — Stone-Geary log-utility constant ΔV:
  Input: "Under Stone-Geary + log utility, the indirect utility gap is constant in income."
  The ln(σ - m̄) terms cancel in the difference, so state the cancellation directly:
    import Mathlib
    open Real

    /-- Under Stone-Geary + log utility, the indirect utility gap ΔV = V_B - V_A
        is exactly constant in income σ. The ln(σ - m̄) terms cancel. -/
    theorem log_utility_constant_delta_v
        (α_A α_B p m_bar σ : ℝ)
        (hαA : 0 < α_A) (hαA1 : α_A < 1)
        (hαB : 0 < α_B) (hαB1 : α_B < 1)
        (hp : 0 < p) (hσ : m_bar < σ) :
        (α_B * Real.log (α_B / p) + (1 - α_B) * Real.log (1 - α_B) + Real.log (σ - m_bar))
        - (α_A * Real.log (α_A / p) + (1 - α_A) * Real.log (1 - α_A) + Real.log (σ - m_bar))
        = (α_B * Real.log (α_B / p) + (1 - α_B) * Real.log (1 - α_B))
        - (α_A * Real.log (α_A / p) + (1 - α_A) * Real.log (1 - α_A)) := by
      sorry

EXAMPLE — Cobb-Douglas output elasticity with respect to capital:
  Input: "For f(K,L) = A·K^α·L^(1-α), the output elasticity w.r.t. capital is α."

  The elasticity is (∂f/∂K) · (K/f).
    ∂f/∂K = α · A · K^(α-1) · L^(1-α)
    K/f   = K / (A · K^α · L^(1-α))

  Multiplying:
    α · A · K^(α-1) · L^(1-α) · K / (A · K^α · L^(1-α))

  The A terms cancel. The L^(1-α) terms cancel. We get:
    α · K^(α-1) · K / K^α = α · K^α / K^α = α

  WRONG formalization (contains rpow):
    (A * α * K ^ (α - 1) * L ^ (1 - α)) * (K / (A * K ^ α * L ^ (1 - α))) = α

  CORRECT formalization (fully simplified, no rpow):
    After ALL exponent terms cancel, the identity reduces to α * K * K⁻¹ = α.

  The correct .lean file:
    import Mathlib
    open Real

    /-- Cobb-Douglas output elasticity w.r.t. capital equals α.
        After substituting ∂f/∂K and f into (∂f/∂K)·(K/f) and canceling
        all A, L, and K^α terms, the expression reduces to α · K · K⁻¹ = α. -/
    theorem cobb_douglas_elasticity_capital (α K : ℝ) (hα : 0 < α) (hα1 : α < 1)
        (hK : K > 0) :
        α * K * K⁻¹ = α := by
      sorry

EXAMPLE — Budget constraint:
  Input: "A consumer with income m facing prices p₁ and p₂ who spends all income
  satisfies p₁·x₁ + p₂·x₂ = m."

  CORRECT formalization:
    State the equality DIRECTLY. Do NOT restate it as an equivalence, an
    existential claim, or a trivially reordered version of the same sum.

    import Mathlib
    open Real

    /-- A consumer who spends all income satisfies the budget equality. -/
    theorem budget_constraint
        (m p₁ p₂ x₁ x₂ : ℝ)
        (hm : m > 0) (hp₁ : p₁ > 0) (hp₂ : p₂ > 0)
        (hspend : p₁ * x₁ + p₂ * x₂ = m) :
        p₁ * x₁ + p₂ * x₂ = m := by
      sorry

GENERAL PRINCIPLE: When you see a claim about elasticities, marginal products,
or ratios of functions — substitute the functional forms, cancel EVERYTHING
that cancels (A, L^(1-α), K^α, etc.), and state ONLY the residual algebraic
identity using basic field operations. The theorem should capture the economic
insight (the elasticity equals α) while being trivially provable.

If the claim CANNOT be faithfully formalized in Lean 4 + Mathlib (requires
measure theory, stochastic calculus, fixed-point theorems, or domain-specific
libraries that don't exist), output:
  import Mathlib
  -- FORMALIZATION_FAILED
  -- Reason: [explanation]
"""

CLASSIFY_SYSTEM_PROMPT = """\
You are an expert in Lean 4 and the Mathlib library.
You will be given a mathematical claim from economics.

Classify it into ONE of these categories:

ALGEBRAIC — The claim reduces to an algebraic identity, equation, or inequality
over real numbers that can be stated directly with standard Lean 4 + Mathlib types.
No custom definitions needed. Examples: "-c·(-γ·c⁻¹) = γ", "budget equality holds",
"sum of even numbers is even".

DEFINABLE — The claim references economic objects (production functions, utility
functions, demand functions, risk measures) that are NOT in Mathlib but CAN be
defined as simple noncomputable functions over ℝ, and the claim itself reduces to
algebra after substituting the functional forms. Examples: "Cobb-Douglas output
elasticity equals α" (define f(K,L) = A·K^α·L^(1-α), then the claim is algebraic),
"CRRA utility has constant RRA" (define u(c), substitute into RRA formula),
"CES production is homogeneous of degree one".

REQUIRES_DEFINITIONS — The claim requires mathematical infrastructure that cannot
be expressed as simple real-valued functions: equilibrium concepts (competitive
equilibrium, Nash equilibrium), welfare theorems, fixed-point arguments,
measure-theoretic constructs, stochastic processes, game-theoretic solution
concepts, or results requiring topology (Brouwer, Kakutani). These need a
domain-specific library that does not exist yet.

For DEFINABLE claims, also state which economic objects need to be defined
and what functional form they take.

OUTPUT FORMAT — respond with ONLY:
  ALGEBRAIC
or
  DEFINABLE: [object1: definition], [object2: definition]
or
  REQUIRES_DEFINITIONS: [1-2 sentence explanation of what's missing]

No other text. No markdown. Just the classification line.
"""

REPAIR_SYSTEM_PROMPT = """\
You are an expert in Lean 4 and Mathlib. A previous attempt to formalize an
economics claim produced a theorem statement that does not compile in Lean 4.

You will be given:
1. The original claim
2. The Lean 4 file that failed
3. The exact error messages from `lake build`

Fix the Lean 4 file so it compiles with only a `sorry` warning.
Apply the MINIMUM changes needed. Do not rewrite from scratch unless the
errors indicate a fundamental approach problem.

REMEMBER: avoid Real.rpow with variable exponents. Use c⁻¹ instead of c ^ (-1).
Prefer algebraic identities that field_simp + ring can handle.

Output ONLY the corrected .lean file. No markdown fences. No explanation.
"""


def build_formalize_prompt(preamble_block: str | None = None) -> str:
    """Build the formalize system prompt, optionally with preamble context.

    When a preamble block is provided, appends instructions telling Leanstral
    to include and use the definitions in the theorem.
    """
    if not preamble_block:
        return FORMALIZE_SYSTEM_PROMPT

    preamble_section = f"""

AVAILABLE DEFINITIONS (preamble):
The following Lean 4 definitions are provided and MUST be included in the
output .lean file AFTER the `import Mathlib` / `open Real` header and BEFORE
the theorem statement. You may reference these definitions in the theorem
hypotheses and conclusion.

```lean
{preamble_block}```

When using these definitions, you may reference them by name in the theorem
statement. The definitions themselves use rpow/log/exp — this is acceptable
because they are noncomputable defs that Lean will unfold during type-checking.
Focus on stating the theorem correctly using these building blocks.
"""
    return FORMALIZE_SYSTEM_PROMPT + preamble_section


DIAGNOSE_SYSTEM_PROMPT = """\
You are an expert in Lean 4 and Mathlib. A formalization attempt has exhausted
all repair cycles and still fails to compile.

You will be given:
1. The original economic claim
2. The last Lean 4 code that was attempted
3. The error messages from lake build

Analyze the failure and respond with ONLY a JSON object (no markdown, no
explanation outside the JSON):

{
  "diagnosis": "1-3 sentence explanation of what went wrong",
  "suggested_fix": "Concrete suggestion for reformulating the claim or fixing the Lean code, or null if genuinely out of scope",
  "fixable": true or false
}

Common failure patterns:
- Type mismatch: theorem signature has wrong types (ℕ vs ℝ, missing coercions)
- Unknown identifier: using a Mathlib name that doesn't exist or was renamed
- Missing hypothesis: variable in denominator without positivity/nonzero hypothesis
- rpow difficulty: variable exponents that should have been simplified away
- Syntax error: malformed Lean 4 syntax
"""
