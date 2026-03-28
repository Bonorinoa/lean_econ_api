# LeanEcon v2 Proposal - Codex

## Purpose

This document is a discussion brief for the next four hours of work. Its goal is not to prescribe implementation details. Its goal is to help a multi-agent conversation decide the best path forward from the current LeanEcon state, with explicit attention to simplicity, evaluation quality, budget constraints, and long-term maintainability.

## Executive Summary

The current evidence suggests that LeanEcon's main bottleneck is not missing capability layers. It is excessive system complexity relative to the maturity of the core product contract.

Recent local evidence:

- The router/runtime correctness pass improved request validation and retrieval telemetry.
- The targeted regression suite is green.
- The current deployed smoke test is healthy.
- But the latest tier-1 benchmark still shows major end-to-end weakness:
  - `raw_claim -> full API`: pass@1 `0.333`, partial rate `0.667`, p50 about `228s`, p95 about `267s`
  - `theorem_stub -> verify`: pass@1 `1.000`
  - `raw_lean -> verify`: pass@1 `0.667`

Interpretation:

- The system is much better at proving already-shaped statements than at end-to-end claim handling.
- This points toward statement shaping, routing complexity, and harness design as the main product risks.
- The highest-ROI next step is likely simplification, not more layers.

## External Evidence and Best-Practice Signal

Recent guidance and research are directionally aligned:

- Anthropic recommends starting with the simplest viable agent pattern and only adding complexity when it demonstrably improves evals.
- OpenAI recommends eval-first iteration, narrow tool surfaces, and reproducible task-specific harnesses rather than broad orchestration by default.
- Recent theorem-proving and autoformalization work suggests that statement quality, decomposition, and proof-shape control matter more than piling on online routing logic.

Useful references:

- Anthropic, "Building effective agents":
  - https://www.anthropic.com/engineering/building-effective-agents
- Anthropic tool-use guidance:
  - https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use
- OpenAI evaluation best practices:
  - https://developers.openai.com/api/docs/guides/evaluation-best-practices
- OpenAI agent evals:
  - https://developers.openai.com/api/docs/guides/agent-evals
- OpenAI reasoning best practices:
  - https://developers.openai.com/api/docs/guides/reasoning-best-practices
- DSP: sketch-guided theorem proving:
  - https://openreview.net/forum?id=SMa9EAovKMC
- Prover Agent:
  - https://openreview.net/forum?id=sPdQfGQccH
- ProofNet:
  - https://openreview.net/forum?id=Zix86UbMGh
- Lean4 autoformalization benchmark:
  - https://openreview.net/forum?id=22ITxc8y5p
- AlphaProof:
  - https://www.nature.com/articles/s41586-025-09833-y

## Working Thesis

LeanEcon should likely split into two tracks:

- `LeanEcon v1`: stabilize and keep deployable with minimal additional scope.
- `LeanEcon v2`: redesign around a smaller product contract, clearer boundaries, and cleaner evals.

The v2 discussion should be guided by one core question:

> What is the minimum agentic system that can reliably transform a natural-language economics claim into a Lean-verifiable result, while remaining open-source friendly and cheap enough to iterate on?

## Proposed Focus for the Next Four Hours

The next four hours should optimize for decision quality, not code volume.

### Hour 1: Decide the v1 and v2 Boundary

#### Motivation

Right now, the project is serving too many goals at once:

- deployment target
- research harness
- MCP/tooling testbed
- provider abstraction layer
- autoformalization playground

That overlap is likely increasing entropy and making regressions hard to interpret.

#### Questions to Answer

- Should v2 live in a clone/new repository, or as a major branch/subtree of this repo?
- What exactly remains in v1?
- What exactly moves to v2?
- Is the near-term objective "stabilize product" or "rebuild architecture"?

#### Options

| Option | Benefits | Costs | Risks | 4-hour ROI |
| --- | --- | --- | --- | --- |
| Refactor in place | Lowest migration friction | High conceptual entanglement | Old assumptions leak into new design | Medium |
| New repo from clone | Clean boundary with reusable assets | Some setup/documentation cost | Short-term duplication | High |
| Empty greenfield repo | Maximum clarity | Highest bootstrap cost | Four hours may produce only scaffolding | Low-Medium |

#### Recommendation

Prefer a new repo from a clone, not a blank start.

Reason:

- It preserves useful Lean assets, tests, and preambles.
- It creates a clean place for a smaller contract and cleaner docs.
- It avoids spending the next four hours rebuilding infrastructure from zero.

### Hour 2: Simplify the Product Contract

#### Motivation

The benchmark gap between `raw_claim` and `theorem_stub` suggests the system is strongest when the contract is narrow and weakest when the contract is overloaded.

Current likely anti-patterns:

- `/verify` is doing too much implicitly.
- formalizer-to-prover handoff has become semantically rich but operationally noisy.
- the system mixes "statement generation," "proof search," and "observability metadata" too tightly.

#### Questions to Answer

- What are the minimum top-level modes the product should support?
- Which outputs must be structured and when?
- Which metadata is operational telemetry only, and should not affect behavior?
- Should human-in-the-loop be a first-class contract or an optional layer?

#### Candidate Simplified Contract

- `classify` or "scope decision"
- `formalize` or "produce candidate Lean statement"
- `verify` or "prove exactly this statement"
- optional `compile/debug`

Everything else should be explicit, not implicit.

#### Cost-Benefit

| Decision | Benefit | Cost | Risk |
| --- | --- | --- | --- |
| Narrow `/verify` to proving supplied theorem only | Better interpretability, lower routing ambiguity | Some current workflows must move elsewhere | Users may need more explicit API usage |
| Keep retrieval/context as telemetry, not steering | Lower search waste, cleaner failure modes | Less "clever" behavior | Might reduce success on some edge cases |
| Force structured output only for unstable boundaries | Cleaner HITL and automation | More design work up front | Over-specifying schemas too early |

#### Recommendation

Use v2 to define a smaller, more explicit contract. Treat formalizer context as advisory data by default, not as prompt fuel.

### Hour 3: Re-engineer the Harnesses from First Principles

#### Motivation

Current harness outputs are useful, but they may be mixing too many objectives:

- product acceptance
- research diagnosis
- prover latency
- theorem faithfulness
- provider benchmarking

This can make the harness itself part of the confusion.

#### Questions to Answer

- Do we need one harness or several sharply scoped ones?
- What exactly counts as success for each stage?
- Which failures should be attributed to theorem shape, prover runtime, provider transport, or Lean environment?
- How should Mathlib search be exposed: native Lean tools, MCP only, or optional extra dependencies?

#### Proposed Harness Split

Instead of one global concept of "benchmark quality," use four eval classes:

1. Statement faithfulness
2. Statement canonicality or proof-friendliness
3. Prover success on fixed statements
4. End-to-end claim-to-proof success

#### Cost-Benefit

| Harness Direction | Benefit | Cost | Risk |
| --- | --- | --- | --- |
| One global harness | Simple to explain | Easy to overfit and misread | Stage failures remain ambiguous |
| Several scoped harnesses | Clear attribution and better iteration | More reporting design | Slightly more maintenance |
| Container-wide generic constraint harness | Useful for safety/runtime envelopes | Can become too abstract | May not help theorem quality directly |

#### Recommendation

Prefer multiple small harnesses with one summary roll-up. The system needs attribution more than it needs a single scoreboard.

#### Additional Principle

Mathlib search should be treated as a pluggable capability, not a foundational architectural assumption.

Good default:

- minimal native Lean/MCP search path in core runtime
- optional expanded search backends behind a provider-style interface

### Hour 4: Decide the Open-Source and Provider Strategy

#### Motivation

Open-source viability matters for cost, governance, datasets, reproducibility, and long-term independence.

The Hugging Face idea is strong, but the project should avoid making HF a substitute for architectural clarity.

#### Questions to Answer

- Should provider abstraction be a first-class v2 contract?
- Should Hugging Face become the default model registry and dataset hub?
- Can the LLM-facing agent layer be cleanly separated from Lean assets and harnesses?
- What is the minimum CI/CD path needed for a serious v2?

#### Cost-Benefit

| Direction | Benefit | Cost | Risk |
| --- | --- | --- | --- |
| HF as central ecosystem dependency | Better OSS posture, datasets, fine-tuning path, model choice | Extra abstraction/design effort | Premature provider generality |
| Mistral-first with optional HF later | Faster short-term work | Higher vendor concentration | Harder migration later |
| Provider-agnostic interface from day one | Better long-term architecture | More up-front design | May over-engineer before contract stabilizes |

#### Recommendation

Design a provider-agnostic interface in v2, but avoid full "plug and play" ambitions until the product contract is simplified.

Hugging Face should likely be central for:

- datasets
- eval artifacts
- model experimentation
- open-source collaboration

But not necessarily as a hard dependency in the very first runtime milestone.

## Suggested Decision Outputs by the End of the Four Hours

The conversation should aim to produce these artifacts:

1. A one-page v1 versus v2 boundary memo
2. A draft v2 API contract with fewer implicit behaviors
3. A harness taxonomy with stage-specific success criteria
4. A provider strategy note covering HF, OSS, and separation of concerns
5. A documentation plan for the new repo or clone
6. A short list of "what not to build yet"

## Budget Constraints to Keep in View

The conversation should stay mindful of four budgets:

### 1. Engineering Budget

- Four hours is enough to decide and outline.
- Four hours is not enough to execute a full greenfield rebuild responsibly.

### 2. Runtime Budget

- Current proving latencies are too high for carefree end-to-end routing.
- Any v2 design that assumes heavy iterative search on every request is suspect.

### 3. Cognitive Budget

- Every hidden lane, override, or merged context object increases debugging cost.
- Simpler contracts will compound in value faster than more "intelligent" orchestration.

### 4. Vendor and Compute Budget

- Multi-provider support is valuable.
- But provider abstraction without eval clarity can mask core product failures.
- Open-source posture matters, but should support simplification rather than distract from it.

## What the Conversation Should Probably Avoid

- Avoid committing to a blank-slate rebuild immediately.
- Avoid treating more routing logic as the default answer.
- Avoid designing a giant all-purpose harness before clarifying stage boundaries.
- Avoid making provider plug-and-play the central problem before the API contract is simplified.
- Avoid assuming that richer formalizer context automatically improves proving.

## Preliminary Recommendation

If the discussion needs a default starting position, this is the recommended one:

### Recommended Path

1. Freeze v1 scope and stabilize only critical fixes.
2. Start v2 in a clone or new repository derived from this one.
3. Redefine the product around a smaller explicit contract.
4. Separate evals into statement-quality, prover-quality, and end-to-end quality.
5. Keep provider abstraction shallow at first.
6. Use Hugging Face as the open-source data and experimentation backbone, not as the first architectural centerpiece.

## High-Value Questions for the Multi-Agent Discussion

1. What should `/verify` mean in v2, exactly?
2. Which current features are true product requirements, and which are research-era scaffolding?
3. What metadata should never influence proving behavior?
4. Do we want v2 to optimize for deployment first, research first, or OSS platform first?
5. What is the smallest harness design that still gives trustworthy attribution?
6. What Lean-related assets must remain tightly coupled to runtime, and what can be separated cleanly?
7. What is the minimum documentation set required before serious v2 implementation begins?

## Closing Position

The current project appears to be suffering less from a lack of intelligence and more from a lack of crisp boundaries. The next four hours should therefore focus on simplification decisions, contract clarity, and eval decomposition. If those are done well, many later implementation choices become easier, cheaper, and safer.
