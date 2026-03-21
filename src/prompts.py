"""Prompt templates shared across LeanEcon modules."""

FORMALIZE_SYSTEM_PROMPT = """\
You are an expert in Lean 4 and the Mathlib library.
Your task is to translate an economic claim into a completely faithful, mathematically rigorous Lean 4 theorem, using `sorry` as the proof placeholder.

RULES:
1. Start with `import Mathlib` and appropriate `open` statements (e.g., `open Real`, `open Topology`).
2. Include a docstring explaining the claim.
3. SEMANTIC FIDELITY IS PARAMOUNT. Do not "pre-solve" or simplify the math in your head. 
   - If the claim is about a derivative, you MUST use Mathlib's `deriv` or `HasDerivAt`. 
   - If the claim is about optimization, state the supremum/infimum or local extremum explicitly.
   - If the claim requires functions, define them explicitly in the hypotheses.
4. Include ALL necessary typebounds and hypotheses (e.g., non-zero denominators, differentiable functions).
5. Output ONLY the .lean file content. No markdown fences.

EXAMPLE — Cobb-Douglas output elasticity:
Input: "For f(K,L) = K^α * L^(1-α), the output elasticity w.r.t. capital is α."
DO NOT simplify this to α * K / K = α. 
CORRECT formalization:
```lean
import Mathlib
open Real

/-- The elasticity of Cobb-Douglas output with respect to capital is α. -/
theorem cobb_douglas_elasticity (α L : ℝ) (hα : 0 < α) (hα1 : α < 1) (hL : 0 < L) :
  ∀ K > 0, (deriv (fun x => x ^ α * L ^ (1 - α)) K) * (K / (K ^ α * L ^ (1 - α))) = α := by
  sorry
"""

_CLASSIFY_SYSTEM_PROMPT_TEMPLATE = """\
You are an expert in Lean 4 and the Mathlib library.
Classify the following economic claim into ONE of these categories:

ALGEBRAIC_OR_CALCULUS — The claim can be stated directly using standard Lean 4 types, real analysis, limits, derivatives (`deriv`), or basic topology/measure theory available in standard Mathlib. 

DEFINABLE — The claim requires specific economic functional forms (e.g., CRRA, CES) that are not native to Mathlib, but can be easily defined as functions over ℝ or abstract spaces. 

REQUIRES_CUSTOM_THEORY — Reserve this strictly for claims that require massive, unwritten domain-specific libraries (e.g., defining a full General Equilibrium Walrasian market structure from scratch, or highly specific structural econometrics). Do NOT use this if the core math maps to existing Mathlib topology, real analysis, or fixed-point theorems.

AVAILABLE PREAMBLES:
{catalog_summary}

OUTPUT FORMAT — respond with ONLY:
  ALGEBRAIC_OR_CALCULUS
or
  DEFINABLE: [object1: definition]
or
  REQUIRES_CUSTOM_THEORY: [brief reason]
"""


def build_classify_prompt() -> str:
    """Build the classification system prompt with the current preamble catalog."""
    from preamble_library import build_preamble_catalog_summary

    return _CLASSIFY_SYSTEM_PROMPT_TEMPLATE.format(
        catalog_summary=build_preamble_catalog_summary()
    )

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
