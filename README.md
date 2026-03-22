# LeanEcon

**Formal verification of mathematical claims in economics papers.**

LeanEcon takes a claim in plain text, LaTeX, or raw Lean 4 and turns it into a
Lean-checked proof using [Leanstral](https://mistral.ai/news/leanstral),
[Lean 4](https://lean-lang.org/), and
[Mathlib](https://leanprover-community.github.io/mathlib4_docs/).

LeanEcon currently defaults to one proving backend behind a swappable prover
interface:

- `leanstral`: Leanstral + `lean-lsp-mcp` with live tool use during proving

> Working prototype. Built March 2026.

## What it does

1. **Formalize**: Leanstral turns the claim into a Lean theorem with
   `:= by sorry`, then Lean checks that the statement itself compiles.
   Optionally pass `preamble_names` to inject bundled economic definitions.
2. **Review**: an API client can inspect or edit the theorem before proving.
3. **Prove**: the agentic prover lets Leanstral call Lean MCP tools and iteratively edit a working proof file.
4. **Verify**: LeanEcon writes an isolated per-run Lean file and checks it with
   `lake env lean`. If Lean accepts the proof without `sorry`, the claim is
   certified.

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

The optional `/classify` endpoint categorizes claims into four paths for
frontend UX (but is **not** required before formalization):

- `ALGEBRAIC`: direct algebraic or calculus claims
- `DEFINABLE`: claims that match bundled LeanEcon preamble definitions
- `MATHLIB_NATIVE`: claims formalizable using direct Mathlib infrastructure
- `REQUIRES_DEFINITIONS`: claims that need custom theory beyond current coverage

Classification is advisory only — the formalizer attempts all claims directly.

## Quick start

### Prerequisites

- Python 3.11+
- [Lean 4](https://leanprover-community.github.io/get_started.html) via elan
- A Mistral API key

### Setup

```bash
git clone https://github.com/Bonorinoa/lean_econ_api.git
cd lean_econ_api

python3 -m venv leanEconAPI_venv
source leanEconAPI_venv/bin/activate
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

1. `POST /api/v1/classify` *(optional — for frontend UX only)*
2. `POST /api/v1/formalize` *(with optional `preamble_names`)*
3. Optional client-side theorem review/edit
4. `POST /api/v1/verify`
5. `GET /api/v1/jobs/{job_id}` or `GET /api/v1/jobs/{job_id}/stream`

`POST /api/v1/verify` is asynchronous and returns HTTP `202` with a `job_id`.
Use polling or SSE to track the job to completion.

If the claim depends on a bundled economic definition, use
[`docs/PREAMBLE_CATALOG.md`](docs/PREAMBLE_CATALOG.md) to choose
`preamble_names` for formalization.

## Evaluation toolkit

LeanEcon now ships a small offline evaluation stack on top of the append-only
log at `logs/runs.jsonl`.

- `scripts/analyze_traces.py` computes deep-trace metrics such as Tool Call Efficiency,
  average Tactic Depth, and error-frequency summaries from persisted prover traces.
- `scripts/semantic_grader.py` uses Leanstral as a semantic referee to score whether
  generated Lean code is a faithful, non-trivial translation of the original claim.
- `scripts/run_uncharted_evals.py` bypasses classification, runs `formalize_claim(...)`
  plus `run_pipeline(...)` with configurable `pass@k`, and writes JSON/Markdown
  reports under `outputs/uncharted_evals/`.

Example commands:

```bash
./leanEconAPI_venv/bin/python scripts/analyze_traces.py --runs-file logs/runs.jsonl --format both

./leanEconAPI_venv/bin/python scripts/semantic_grader.py \
  --claim "Under CRRA utility, relative risk aversion is constant." \
  --theorem-file examples/crra_pass.lean

./leanEconAPI_venv/bin/python scripts/run_uncharted_evals.py test_cases/uncharted_claims.jsonl --pass-k 5
```

Example calls:

```bash
curl -X POST http://localhost:8000/api/v1/classify \
  -H "Content-Type: application/json" \
  -d '{"raw_claim":"Under CRRA utility, relative risk aversion is constant and equal to gamma."}'
```

```bash
curl -X POST http://localhost:8000/api/v1/formalize \
  -H "Content-Type: application/json" \
  -d '{"raw_claim":"Under CRRA utility, relative risk aversion is constant and equal to gamma.","preamble_names":["crra_utility"]}'
```

```bash
curl -i -X POST http://localhost:8000/api/v1/verify \
  -H "Content-Type: application/json" \
  -d '{"theorem_code":"import Mathlib\nopen Real\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  sorry","explain":true}'
```

The response body is:

```json
{"job_id":"<JOB_ID>","status":"queued"}
```

```bash
curl -N http://localhost:8000/api/v1/jobs/<JOB_ID>/stream
```

```bash
curl http://localhost:8000/api/v1/jobs/<JOB_ID>
```

```bash
curl -X POST http://localhost:8000/api/v1/explain \
  -H "Content-Type: application/json" \
  -d '{"original_claim":"1 + 1 = 2","verification_result":{"success":true,"proof_generated":true,"formalization_failed":false}}'
```

```bash
curl http://localhost:8000/api/v1/metrics
```

```bash
curl http://localhost:8000/api/v1/cache/stats
```

## Deployment

LeanEcon requires Lean 4, Mathlib, and a local Lean workspace. The Docker image
still performs a build-time `lake build` to warm the workspace and caches, but
runtime verification uses isolated per-run files compiled with `lake env lean`.
This means it cannot run on serverless platforms such as Vercel or static
frontend hosts.

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
    -> [formalizer.py] formalize + sorry-validate (classify is optional)
    -> [API client] optional theorem review/edit
    -> [pipeline.py] agentic proof orchestration
        -> [prover_backend.py] swappable prover dispatch
        -> [agentic_prover.py] Leanstral + MCP + working proof file
    -> [lean_verifier.py] isolated temp-file verification via `lake env lean`
    -> [eval_logger.py] JSONL run log with deep traces
    -> [evaluation scripts] trace analysis + semantic grading + uncharted evals
    -> [FastAPI / CLI] results + metrics
```

```text
src/
├── api.py                   FastAPI service entry point
├── pipeline.py              Shared orchestration and agentic prover dispatch
├── prover_backend.py        Prover protocol and registry
├── formalizer.py            Leanstral formalization (classify is separate/optional)
├── leanstral_utils.py       Shared Leanstral API helpers
├── agentic_prover.py        Leanstral Conversations API + MCP loop
├── mcp_runtime.py           Lean MCP session helpers and query utilities
├── preamble_library.py      File-backed preamble metadata and lookup helpers
├── proof_file_controller.py Working-file management for agentic proving
├── lean_verifier.py         Final isolated-file Lean verification
├── eval_logger.py           Append-only JSONL structured logging
├── eval_metrics.py          Shared evaluation-metric helpers
├── semantic_alignment.py    Semantic grading helpers
└── mcp_smoke_test.py        Lean MCP smoke test
```

```text
scripts/
├── analyze_traces.py        Offline deep-trace analyzer for runs.jsonl
├── semantic_grader.py       CLI semantic-alignment grader
├── run_uncharted_evals.py   pass@k advanced-claim evaluation harness
└── run_phase1_stress_tests.py
```

## How verification works

Lean 4 is a dependently typed programming language where proofs are programs.
LeanEcon's verifier writes each candidate proof to its own temporary Lean file
and runs `lake env lean` on that file. When that check succeeds with no errors
and no `sorry`, the Lean kernel has checked every logical step from axioms.
This is not LLM confidence; it is a machine-checked proof.

Because verification no longer routes through a shared `LeanEcon/Proof.lean`,
multiple verify jobs can run concurrently without overwriting each other's
proof files.

Leanstral generates candidate proofs. Lean verifies them.

The persisted log now records rich `tool_trace` and `tactic_calls` data with a
`trace_schema_version`, plus the full `original_raw_claim`, so offline
evaluation scripts can analyze proving behavior without re-running old jobs.

## Limitations

- Verified examples are still mostly algebraic identities over the reals.
- Proof generation is stochastic. A claim may pass in one run and fail in another.
- `Real.rpow`-heavy claims remain more brittle than simple algebraic equalities.
- The current Leanstral endpoint is a labs model, not a permanent production API.

## Docs

- [`docs/MCP_AGENTIC_PROVER_BRIEF.md`](docs/MCP_AGENTIC_PROVER_BRIEF.md): current MCP-first prover design and status
- [`docs/API.md`](docs/API.md): endpoint contract and agent-oriented usage guide
- [`docs/PREAMBLE_CATALOG.md`](docs/PREAMBLE_CATALOG.md): generated catalog of reusable preamble modules
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md): Docker-based local deployment notes
- [`docs/ROADMAP.md`](docs/ROADMAP.md): current sprint and post-sprint priorities
- [`docs/BUILD_LOG.md`](docs/BUILD_LOG.md): chronological implementation log
- [`docs/skill/SKILL.md`](docs/skill/SKILL.md): agent integration skill for LeanEcon clients
- [`docs/skill/references/endpoints.md`](docs/skill/references/endpoints.md): compact endpoint reference
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
