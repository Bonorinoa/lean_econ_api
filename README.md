# LeanEcon

**Formal verification of mathematical claims in economics papers.**

LeanEcon takes a claim in plain text, LaTeX, or raw Lean 4 and turns it into a
Lean-checked proof using [Leanstral](https://mistral.ai/news/leanstral),
[Lean 4](https://lean-lang.org/), and
[Mathlib](https://leanprover-community.github.io/mathlib4_docs/).

LeanEcon now uses a single proving backend:

- `agentic`: Leanstral + `lean-lsp-mcp` with live tool use during proving

> Working prototype. Built March 2026.

## What it does

1. **Classify + formalize**: Leanstral turns the claim into a Lean theorem with
   `:= by sorry`, then Lean checks that the statement itself compiles.
2. **Review**: an API client can inspect or edit the theorem before proving.
3. **Prove**: the agentic prover lets Leanstral call Lean MCP tools and iteratively edit a working proof file.
4. **Verify**: `lake build` is the final authority. If Lean accepts the proof
   without `sorry`, the claim is certified.

## Current examples

| Claim | Domain | Result |
|-------|--------|--------|
| CRRA utility has constant relative risk aversion | Microeconomics | Verified |
| Indirect utility gap is constant in income (Stone-Geary + log utility) | Macro / Cultural economics | Verified |
| Budget equality under a spending-all-income hypothesis | Microeconomics | Verified |
| Every even natural number has the form `2n` | General mathematics | Verified |
| The sum of two even natural numbers is even | General mathematics | Verified |
| Doubling a natural number yields an even number | General mathematics | Verified |
| Cobb-Douglas output elasticity with respect to capital | Production theory | Improved in agentic mode, but still stochastic |

See `examples/` for committed Lean files and verification reports. Those
artifacts are intentionally conservative: the saved Cobb-Douglas example still
documents the earlier limitation, even though the new agentic path now
succeeds on some runs.

The classifier can also reject claims that require missing economic
definitions. Earlier runs, for example, correctly rejected welfare-theorem
style claims as `REQUIRES_DEFINITIONS`.

## Quick start

### Prerequisites

- Python 3.11+
- [Lean 4](https://leanprover-community.github.io/get_started.html) via elan
- A Mistral API key

### Setup

```bash
git clone https://github.com/Bonorinoa/econ_lean_prover_poc.git
cd econ_lean_prover_poc

python3 -m venv econProver_venv
source econProver_venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your MISTRAL_API_KEY

cd lean_workspace
lake exe cache get
lake build
cd ..
```

### Run

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` for the generated Swagger UI.

For a workflow-oriented reference aimed at frontend agents, see
[`docs/API.md`](docs/API.md).

### API workflow

The first API cut is intentionally multi-step so frontend clients can preserve
the review/edit step:

1. `POST /api/classify`
2. `POST /api/formalize`
3. Optional client-side theorem review/edit
4. `POST /api/verify`

Example calls:

```bash
curl -X POST http://localhost:8000/api/classify \
  -H "Content-Type: application/json" \
  -d '{"raw_claim":"Under CRRA utility, relative risk aversion is constant and equal to gamma."}'
```

```bash
curl -X POST http://localhost:8000/api/formalize \
  -H "Content-Type: application/json" \
  -d '{"raw_claim":"Under CRRA utility, relative risk aversion is constant and equal to gamma."}'
```

```bash
curl -X POST http://localhost:8000/api/verify \
  -H "Content-Type: application/json" \
  -d '{"theorem_code":"import Mathlib\nopen Real\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  sorry"}'
```

## Deployment

LeanEcon requires Lean 4, Mathlib, and a local `lake build` environment.
This means it cannot run on serverless platforms such as Vercel or
static frontend hosts.

For deployment, use Docker:

```bash
docker build -t leanecon .
docker run -p 8000:8000 -e MISTRAL_API_KEY=your_key_here leanecon
```

A Dockerfile is provided at the project root. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for details.

## Architecture

```text
User Input (LaTeX / text / raw Lean)
    -> [FastAPI] classify / formalize / verify endpoints
    -> [formalizer.py] classify + formalize + sorry-validate
    -> [API client] optional theorem review/edit
    -> [pipeline.py] agentic proof orchestration
        -> [agentic_prover.py] Leanstral + MCP + working proof file
    -> [lean_verifier.py] lake build
    -> [FastAPI / CLI] results + logs
```

```text
src/
├── api.py                   FastAPI service entry point
├── pipeline.py              Shared orchestration and agentic prover dispatch
├── formalizer.py            Leanstral classification + formalization
├── leanstral_utils.py       Shared Leanstral API helpers
├── agentic_prover.py        Leanstral Conversations API + MCP loop
├── mcp_runtime.py           Lean MCP session helpers and query utilities
├── preamble_library.py      File-backed preamble metadata and lookup helpers
├── proof_file_controller.py Working-file management for agentic proving
├── lean_verifier.py         Final lake build verification
├── eval_logger.py           Append-only JSONL structured logging
└── mcp_smoke_test.py        Lean MCP smoke test
```

## How verification works

Lean 4 is a dependently typed programming language where proofs are programs.
When `lake build` succeeds with no errors and no `sorry`, the Lean kernel has
checked every logical step from axioms. This is not LLM confidence; it is a
machine-checked proof.

Leanstral generates candidate proofs. Lean verifies them.

## Limitations

- Verified examples are still mostly algebraic identities over the reals.
- Proof generation is stochastic. A claim may pass in one run and fail in another.
- `Real.rpow`-heavy claims remain more brittle than simple algebraic equalities.
- The current Leanstral endpoint is a labs model, not a permanent production API.

## Docs

- [`docs/MCP_AGENTIC_PROVER_BRIEF.md`](docs/MCP_AGENTIC_PROVER_BRIEF.md): current MCP-first prover design and status
- [`docs/API.md`](docs/API.md): endpoint contract and agent-oriented usage guide
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md): Docker-based local deployment notes
- [`docs/ROADMAP.md`](docs/ROADMAP.md): current sprint and post-sprint priorities
- [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md): chronological implementation log
- [`docs/leanstral_architecture.html`](docs/leanstral_architecture.html): visual architecture artifact

## Roadmap

See [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Built with

- Python 3.11+
- [Lean 4](https://lean-lang.org/) v4.28.0
- [Mathlib](https://leanprover-community.github.io/mathlib4_docs/) v4.28.0
- [Leanstral](https://mistral.ai/news/leanstral) (`labs-leanstral-2603`)
- [FastAPI](https://fastapi.tiangolo.com/)
- Uvicorn
