---
name: lean4-econ
description: "Economic domain patterns for Lean 4 formalization. Use this skill whenever formalizing economic claims in Lean 4, debugging formalization failures for economic theorems, searching Mathlib for economic concepts (utility, production, optimization, fixed points, topology for economics), writing or improving LeanEcon formalizer/classifier prompts, expanding the preamble library, or diagnosing why a claim failed to formalize. Triggers on: formalization errors like 'Unknown identifier', 'failed to synthesize instance', or 'unknown module prefix' in economic contexts; any mention of Mathlib paths for economics; preamble expansion; formalizer prompt engineering; contraction mapping, Bellman, Hessian, envelope theorem, or welfare theorem formalization. Also trigger when reviewing uncharted_claims evaluation results or planning which claims the system should handle next. Complements the lean4 skill (general Lean 4 proving) by adding economics-specific Mathlib navigation and formalization patterns."
---

# Lean 4 Economic Formalization Patterns

This skill maps economic concepts to their correct Mathlib representations. It exists because the #1 failure mode in LeanEcon is the formalizer hallucinating Mathlib paths — generating `import Topology` when it should be `import Mathlib.Topology.Basic`, or using `StrictConcave` when the actual identifier is `StrictConcaveOn`.

**When to use this skill:** Before writing any Lean formalization for an economic claim, consult the Mathlib mappings below. When diagnosing formalization failures, check the error against the common failure patterns. When expanding preamble entries or improving the formalizer prompt, use the import templates.

**Relationship to the lean4 skill:** The lean4 skill covers general Lean 4 theorem proving — tactics, cycle engines, LSP tools, and proof strategies. This skill covers the domain layer: which Mathlib modules contain the math that economists need, how to set up type class contexts for economic models, and what formalization patterns work for different claim types.

## Core principle: search before formalize

The lean-lsp-mcp tools available to the agentic prover are also the right tools for formalization. Before generating a Lean theorem stub, the formalizer should use:

- `lean_local_search("keyword")` — fast local + Mathlib search (unlimited calls)
- `lean_leansearch("natural language query")` — semantic search (3 per 30s window)
- `lean_loogle("type pattern")` — type-pattern search (unlimited if local mode)
- `lean_leanfinder("goal or query")` — semantic, goal-aware (10 per 30s window)

Example: Before formalizing "the Bellman operator is a contraction," search for `lean_local_search("ContractingWith")` and `lean_leansearch("contraction mapping fixed point")` to find the actual Mathlib identifiers.

## Mathlib import mappings for economics

### Analysis and calculus (most economic claims land here)

| Concept | Correct Mathlib import | Key identifiers |
|---|---|---|
| Real numbers, basic ops | `Mathlib.Data.Real.Basic` | `ℝ`, `Real` |
| Derivatives | `Mathlib.Analysis.Calculus.Deriv.Basic` | `HasDerivAt`, `deriv`, `DifferentiableAt` |
| Partial derivatives | `Mathlib.Analysis.Calculus.FDeriv.Basic` | `HasFDerivAt`, `fderiv` |
| Mean value theorem | `Mathlib.Analysis.Calculus.MeanValue` | `exists_ratio_hasDerivAt_eq_ratio_slope` |
| Power functions | `Mathlib.Analysis.SpecialFunctions.Pow.Real` | `Real.rpow`, `rpow_natCast` |
| Logarithm | `Mathlib.Analysis.SpecialFunctions.Log.Basic` | `Real.log`, `Real.log_rpow` |
| Exponential | `Mathlib.Analysis.SpecialFunctions.ExpDeriv` | `Real.exp`, `hasDerivAt_exp` |
| Integration | `Mathlib.MeasureTheory.Integral.Bochner` | `∫`, `MeasureTheory.integral` |

### Convexity and optimization (critical for welfare, utility theory)

| Concept | Correct Mathlib import | Key identifiers |
|---|---|---|
| Convex sets | `Mathlib.Analysis.Convex.Basic` | `Convex`, `ConvexOn` |
| Concave functions | `Mathlib.Analysis.Convex.Basic` | `ConcaveOn`, `StrictConcaveOn` |
| Convex functions | `Mathlib.Analysis.Convex.Basic` | `ConvexOn`, `StrictConvexOn` |
| Jensen's inequality | `Mathlib.Analysis.Convex.Jensen` | (check current API) |
| Extreme value theorem | `Mathlib.Topology.Order.Basic` + `Mathlib.Topology.ContinuousOn` | `IsCompact.exists_isMinOn`, `IsCompact.exists_isMaxOn` |

**Common error:** The formalizer generates `StrictConcave f` — this doesn't exist. The correct form is `StrictConcaveOn ℝ (Set.univ) f` or `StrictConcaveOn ℝ s f` for a specific set `s`.

### Topology (needed for fixed-point theorems, existence results)

| Concept | Correct Mathlib import | Key identifiers |
|---|---|---|
| Topological spaces | `Mathlib.Topology.Basic` | `TopologicalSpace`, `IsOpen`, `IsClosed` |
| Compactness | `Mathlib.Topology.Compactness.Compact` | `IsCompact`, `CompactSpace` |
| Continuity | `Mathlib.Topology.ContinuousFunction.Basic` | `Continuous`, `ContinuousOn` |
| Metric spaces | `Mathlib.Topology.MetricSpace.Basic` | `MetricSpace`, `dist` |
| Normed spaces | `Mathlib.Analysis.NormedSpace.Basic` | `NormedAddCommGroup`, `NormedSpace` |
| Complete metric spaces | `Mathlib.Topology.MetricSpace.Completion` | `CompleteSpace` |
| Banach fixed point | `Mathlib.Topology.MetricSpace.Contracting` | `ContractingWith`, `ContractingWith.fixedPoint` |
| Brouwer fixed point | Not in Mathlib as of early 2026 — formalization requires custom setup |

**Critical:** Never `import Topology` — it's always `import Mathlib.Topology.Basic` or a more specific submodule. The bare module prefix `Topology` does not exist.

### Fixed-point theory (Bellman, value function iteration)

For the Banach contraction mapping theorem:

```lean
import Mathlib.Topology.MetricSpace.Contracting

-- The key type: ContractingWith measures contraction rate
-- ContractingWith K f means: ∀ x y, dist (f x) (f y) ≤ K * dist x y
-- where K : ℝ≥0 and K < 1

-- The fixed-point theorem gives:
-- ContractingWith.fixedPoint : the unique fixed point
-- ContractingWith.isFixedPt_fixedPoint : f (fixedPoint) = fixedPoint
-- ContractingWith.tendsto_iterate_fixedPoint : iterates converge
```

For Bellman operator formalization, the pattern is:
1. Define the operator as a function on a complete metric space (or a Banach space)
2. Prove `ContractingWith K T` where `T` is the Bellman operator and `K` is the discount factor
3. Apply `ContractingWith.fixedPoint` to get the value function

**Current limitation:** Mathlib's `ContractingWith` works on `MetricSpace` instances. For the supremum-norm metric on function spaces (needed for Bellman), you need `BoundedContinuousFunction` from `Mathlib.Topology.ContinuousFunction.Bounded`, which has a `MetricSpace` instance.

### Linear algebra (input-output models, Hessian matrices)

| Concept | Correct Mathlib import | Key identifiers |
|---|---|---|
| Matrices | `Mathlib.Data.Matrix.Basic` | `Matrix`, `Matrix.mul` |
| Determinant | `Mathlib.LinearAlgebra.Matrix.Determinant` | `Matrix.det` |
| Eigenvalues | `Mathlib.LinearAlgebra.Eigenspace.Basic` | `Module.End.eigenspace` |
| Positive definite | `Mathlib.LinearAlgebra.Matrix.PosDef` | `Matrix.PosDef`, `Matrix.PosSemidef` |
| Bilinear forms | `Mathlib.LinearAlgebra.BilinearForm.Basic` | `BilinForm` |

**Common error:** The formalizer generates bare `hessian` — this doesn't exist as a standalone function in Mathlib. The Hessian must be constructed via second-order Fréchet derivatives: `fderiv ℝ (fderiv ℝ f)`. For matrix representation, you need an explicit basis.

### Measure theory (probability, stochastic models)

| Concept | Correct Mathlib import | Key identifiers |
|---|---|---|
| Measure spaces | `Mathlib.MeasureTheory.Measure.MeasureSpace` | `MeasureSpace`, `MeasurableSpace` |
| Probability | `Mathlib.Probability.ProbabilityMassFunction.Basic` | `MeasureTheory.IsProbabilityMeasure` |
| Expectation | `Mathlib.Probability.Notation` | `𝔼[X]`, `MeasureTheory.integral` |
| Conditional expectation | `Mathlib.MeasureTheory.Function.ConditionalExpectation.Basic` | `MeasureTheory.condexp` |

**Note:** Measure-theoretic claims are currently out of LeanEcon's reliable scope. The formalizer can attempt them but expect formalization failure. The type class setup is complex — `MeasurableSpace`, `MeasureSpace`, `IsProbabilityMeasure` must all be provided in the right order.

### Order theory and lattices (monotone comparative statics)

| Concept | Correct Mathlib import | Key identifiers |
|---|---|---|
| Partial orders | `Mathlib.Order.Basic` | `PartialOrder`, `LE`, `Monotone` |
| Lattices | `Mathlib.Order.Lattice` | `Lattice`, `CompleteLattice` |
| Supremum/infimum | `Mathlib.Order.ConditionallyCompleteLattice.Basic` | `sSup`, `sInf`, `iSup`, `iInf` |
| Tarski fixed point | `Mathlib.Order.FixedPoints` | `OrderHom.lfp`, `OrderHom.gfp` |

## Formalization templates by claim type

### Algebraic identity (highest success rate)

```lean
import Mathlib
-- import LeanEcon.PreambleName  (if using preamble)

theorem claim_name
    (x : ℝ) (hx : x > 0)  -- state hypotheses explicitly
    : lhs = rhs := by
  sorry
```

Tactics that close these: `field_simp [ne_of_gt hx]` → `ring`, or `simp` → `ring`.

### Derivative claim (medium success rate)

```lean
import Mathlib.Analysis.Calculus.Deriv.Basic
import Mathlib.Analysis.SpecialFunctions.Pow.Deriv
-- import LeanEcon.PreambleName

theorem marginal_product
    (K L : ℝ) (hK : K > 0) (hL : L > 0)
    (A α : ℝ) (hA : A > 0) (hα : 0 < α) (hα1 : α < 1)
    : HasDerivAt (fun k => A * k ^ α * L ^ (1 - α)) 
                 (α * A * K ^ (α - 1) * L ^ (1 - α)) K := by
  sorry
```

Key: Use `HasDerivAt` (not `deriv` directly) for cleaner goals. The Lean 4 rpow (`^`) on reals with real exponents is `Real.rpow` and requires `import Mathlib.Analysis.SpecialFunctions.Pow.Real`.

### Existence/uniqueness (low success rate, improving)

```lean
import Mathlib.Topology.Basic
import Mathlib.Analysis.Calculus.MeanValue
import Mathlib.Topology.ContinuousFunction.Basic

theorem steady_state_exists
    (f : ℝ → ℝ)
    (hf_cont : ContinuousOn f (Set.Ici 0))
    (hf_zero : f 0 = 0)
    (hf_inada : ∀ M > 0, ∃ K > 0, f K > M)
    (s δ n : ℝ) (hs : 0 < s) (hs1 : s < 1) (hδ : 0 < δ) (hn : 0 ≤ n)
    : ∃ k > 0, s * f k = (δ + n) * k := by
  sorry
```

Note: Avoid `∃!` (unique existence) unless you have concavity hypotheses strong enough to prove uniqueness. The eval showed the prover struggling with `∃!` goals even when existence was reachable.

### Type class setup patterns

When formalizing claims that need metric/normed space structure:

```lean
-- WRONG: Product type doesn't automatically get NontriviallyNormedField
variable [NontriviallyNormedField (ℝ × X)]  -- will fail

-- RIGHT: Use component-wise structure
variable {X : Type*} [NormedAddCommGroup X] [NormedSpace ℝ X]

-- For function spaces (e.g., Bellman operator domain):
variable {α : Type*} [TopologicalSpace α] [CompactSpace α]
-- Use BoundedContinuousFunction α ℝ as the space, which has MetricSpace instance
```

## Common formalization errors and fixes

| Error | Cause | Fix |
|---|---|---|
| `unknown module prefix 'Topology'` | Bare `import Topology` | Use `import Mathlib.Topology.Basic` |
| `Unknown identifier 'StrictConcave'` | Doesn't exist | Use `StrictConcaveOn ℝ s f` from `Mathlib.Analysis.Convex.Basic` |
| `Unknown identifier 'hessian'` | Doesn't exist as standalone | Construct via `fderiv ℝ (fderiv ℝ f)` |
| `failed to synthesize NontriviallyNormedField (ℝ × X)` | Product types need explicit structure | Provide `NormedAddCommGroup` and `NormedSpace` on components |
| `Proof contains 'sorry'` | Formalizer didn't remove sorry placeholder | Expected — sorry is intentional before verification |
| `No goals to be solved` | Extra tactic after goal already closed | Remove trailing tactics; use `lean_goal` to check state |

## Classifier and formalizer prompt engineering

### Classifier considerations

The classifier now has a Mathlib-aware path:

- `ALGEBRAIC` for direct algebraic or calculus claims
- `DEFINABLE` for claims covered by LeanEcon preamble modules
- `MATHLIB_NATIVE` for claims that are outside the preamble library but likely formalizable with direct Mathlib imports
- `REQUIRES_DEFINITIONS` for claims that still need custom theory

This means fixed-point, topology, convexity, and related claims may be routed to `MATHLIB_NATIVE` instead of being rejected immediately. The classifier also includes rescue logic: if `MATHLIB_NATIVE` or `REQUIRES_DEFINITIONS` is predicted but preamble keyword matching finds bundled coverage, the claim is upgraded to `DEFINABLE`.

**Options for expanding scope:**
1. **Add new preamble entries** for fixed-point theory, optimization, and dynamic programming — this is the cleanest path since it stays within the existing architecture.
2. **Strengthen the `MATHLIB_NATIVE` path** by using lean-lsp-mcp or curated import templates to discover the right Mathlib imports more reliably.
3. **Soften the reject boundary further** by checking Mathlib coverage (via search tools) before returning `REQUIRES_DEFINITIONS`.

### Formalizer prompt improvements

The formalizer system prompt should include:

1. **Explicit import path guidance** — never generate bare module prefixes. Always use full `Mathlib.X.Y.Z` paths.
2. **Type class checklist** — before generating a formalization, verify that the types used have the required instances. Don't assume `MetricSpace` on products or function spaces without checking.
3. **Identifier verification** — use `lean_local_search` to verify that identifiers exist before using them in the formalization.
4. **Fallback strategy** — if the first formalization attempt uses an unknown identifier, the retry should search Mathlib for the correct one rather than guessing a different wrong name.

### Search-assisted formalization pattern

For claims in uncharted territory, the formalizer should follow this workflow:

```
1. Parse the claim into its core mathematical components
2. For each component, search Mathlib:
   - lean_local_search("component keyword")
   - lean_leansearch("natural language description")
3. If all components have Mathlib counterparts, construct the formalization using the found identifiers
4. If any component is missing, report which specific concepts lack Mathlib coverage
5. Validate the formalization with lean_run_code before returning
```

This search-first approach would have caught the `StrictConcave`, `hessian`, and `Topology` errors before they became formalization failures.

## Preamble library expansion priorities

Based on the eval results, these are the highest-value additions:

1. **Contraction mapping** — wrap `ContractingWith` from `Mathlib.Topology.MetricSpace.Contracting` with economic domain notation (discount factor, operator)
2. **Bellman operator** — define the operator on `BoundedContinuousFunction` and prove it's contracting under standard assumptions
3. **Concavity toolkit** — provide `StrictConcaveOn` wrappers with economic variable names
4. **Optimization** — first-order conditions using `HasFDerivAt` with economic context
5. **Inada conditions** — formalize the standard Inada conditions as a structure or type class

Each preamble entry needs: a compiled `.lean` file in `lean_workspace/LeanEcon/`, a metadata entry in `PREAMBLE_LIBRARY` (Python dict) with keywords, and ideally proven helper lemmas.
