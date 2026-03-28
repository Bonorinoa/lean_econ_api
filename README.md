# LeanEcon

LeanEcon is a single-repo, Apache-2.0 Lean-backed verification service for
mathematical claims in economics and adjacent mathematics. It turns plain
language, LaTeX, or Lean 4 inputs into Lean-checked results using Lean 4,
Mathlib, and the current Leanstral-backed proving loop.

> **Active development has moved to [LeanEcon v2](https://github.com/Bonorinoa/leanecon_v2).**
> This repository (v1) is in maintenance-only mode. Critical fixes only.
> See the v2 repo for the provider-agnostic architecture, autoresearch loops,
> and the simplified API contract.

The public workflow is intentionally explicit:

1. `POST /api/v1/classify` for optional scope hints and preamble suggestions
2. `POST /api/v1/formalize` to shape a claim into a Lean theorem stub
3. Review or edit the theorem text
4. `POST /api/v1/verify` to queue proof generation and final Lean checking
5. Poll `GET /api/v1/jobs/{job_id}` or stream `GET /api/v1/jobs/{job_id}/stream`
6. Call `POST /api/v1/explain` after the job finishes if you want a summary

If you already have Lean theorem code with `:= by sorry`, skip formalization and
go straight to `/verify`. If you already have complete Lean code and want a
direct compiler check, use `/api/v1/lean_compile` as an optional
compile/debug primitive. It is not the default workflow.

## What LeanEcon Is

- a Lean-backed API for classifying, formalizing, proving, and explaining claims
- a human-in-the-loop workflow for editing theorem statements before proving
- a deterministic Lean-kernel check at the end of every successful verification
- a benchmarked system that tries to stay honest about where the hard lanes are

## Current Lane Reality

The current benchmark story is stable:

- strongest public lanes: `theorem_stub -> verify` and `raw_lean -> verify`
- weakest public lane: `raw_claim -> full API`
- bounded formalization is still mixed on the tier-1 core slice and frontier
  claims

From the latest completed tier-1 full benchmark report
[`benchmarks/reports/tier1_core_selected_full_full_20260328T181026Z.md`](benchmarks/reports/tier1_core_selected_full_full_20260328T181026Z.md):

- `raw_claim -> full API`: `pass@1 = 0.000`
- `theorem_stub -> verify`: `pass@1 = 1.000`
- `raw_lean -> verify`: `pass@1 = 1.000`

The latest completed tier-1 formalizer-only report
[`benchmarks/reports/tier1_core_formalizer_only_20260328T174455Z.md`](benchmarks/reports/tier1_core_formalizer_only_20260328T174455Z.md)
shows the bounded claim-shaping gate at `pass@1 = 0.667`, with semantic `>=4`
on `0.750` of graded completions.

The latest completed tier-2 frontier formalizer-only report
[`benchmarks/reports/tier2_frontier_formalizer_only_20260325T065620Z.md`](benchmarks/reports/tier2_frontier_formalizer_only_20260325T065620Z.md)
shows `pass@1 = 0.667`, with the extreme-value repair case still failing.

LeanEcon remains strongest when the statement is already in good Lean form.
The frozen v1 gap is still end-to-end `raw_claim` reliability; the latest
selected tier-1 rerun restored strong theorem-stub and raw-Lean verification,
but raw claims still fail on that slice.

## Pricing And Status

Leanstral is an external dependency, not a promise of stable pricing, quota, or
permanent availability. LeanEcon itself does not guarantee a stably free model
tier. Treat any cost or model-status claim as provisional unless the repo says
otherwise.

Provider usage telemetry and estimated cost bounds are observability fields
only. They are conservative planning signals, not billing output or a public
pricing promise.

## Canonical Docs

- [`docs/API.md`](docs/API.md): operational canonical API guide
- [`docs/HARNESS_FORMALIZER_PROVER_REPORT.tex`](docs/HARNESS_FORMALIZER_PROVER_REPORT.tex): canonical architecture and trust-model audit
- [`docs/FINAL_V1_BENCHMARK.md`](docs/FINAL_V1_BENCHMARK.md): final maintenance-mode validation and benchmark baseline
- [`docs/leanstral_architecture.html`](docs/leanstral_architecture.html): archived historical note; not the current architecture source of truth
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md): local Docker and deployment notes
- [`docs/MCP_AGENTIC_PROVER_BRIEF.md`](docs/MCP_AGENTIC_PROVER_BRIEF.md): archived background note
- [`CONTRIBUTING.md`](CONTRIBUTING.md): lightweight contributor guidance
- [`NOTICE`](NOTICE): Apache-2.0 notice file
- [`TRADEMARK.md`](TRADEMARK.md): short brand and trademark guidance

Security and hardening fixes currently route through the normal contribution
flow in [`CONTRIBUTING.md`](CONTRIBUTING.md); there is no separate monitored
security inbox for the API right now.

## Quick Start

### Prerequisites

- Python 3.11+
- Lean 4 via `elan`
- a Mistral API key

### Setup

```bash
python3 -m venv leanEconAPI_venv
source leanEconAPI_venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add your MISTRAL_API_KEY

cd lean_workspace
lake exe cache get
lake build
cd ..
```

### Run

```bash
./leanEconAPI_venv/bin/python -m uvicorn src.api:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/docs` for the generated Swagger UI.

## Validation

The lightweight local checks are:

```bash
./leanEconAPI_venv/bin/ruff check src tests scripts
./leanEconAPI_venv/bin/python -m pytest -m "not live and not slow" --tb=short -q
./leanEconAPI_venv/bin/python src/mcp_smoke_test.py
cd lean_workspace && lake build && cd ..
```

For deployed API gating, also run:

```bash
./leanEconAPI_venv/bin/python scripts/production_smoke.py \
  --base-url https://leaneconapi-production.up.railway.app \
  --poll-interval 1 \
  --max-polls 10
```

Treat that command as passing only when it exits `0` and reports
`summary.overall_ok = true`.

Latest local maintenance sweep on 2026-03-28:

- `./leanEconAPI_venv/bin/ruff check src tests scripts`: passed
- `./leanEconAPI_venv/bin/python -m pytest -m "not live and not slow" --tb=short -q`:
  `253 passed, 13 deselected`
- `./leanEconAPI_venv/bin/python src/mcp_smoke_test.py`: exited `0`
- `cd lean_workspace && lake build && cd ..`: passed

Most recent Railway production smoke:

- `./leanEconAPI_venv/bin/python scripts/production_smoke.py --base-url https://leaneconapi-production.up.railway.app --poll-interval 1 --max-polls 10`:
  exited `0` on 2026-03-28; `/health`, `/openapi.json`, `/api/v1/metrics`,
  `/api/v1/cache/stats`, classify, and formalize all returned success, and the
  sample verify job completed on the
  first poll from cache with `current_stage = "cache"` and `partial = false`

For API-specific smoke checks, see `tests/test_api_smoke.py`.

## License

This repository is licensed under Apache-2.0. See
[`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
