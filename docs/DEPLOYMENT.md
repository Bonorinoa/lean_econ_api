# LeanEcon Deployment

LeanEcon must run with local Lean tooling available because final verification
depends on the local Lean toolchain inside `lean_workspace/`. Runtime verify
jobs use isolated per-run temp files compiled with `lake env lean`.

LeanEcon v1 is in maintenance-only mode. Use this document to keep the current
service stable; target `https://github.com/Bonorinoa/leanecon_v2` for new
deployment architecture work.

## Local Docker

Treat Docker as the primary pre-deploy validation target. Railway rebuilds take
long enough that they should be used for confirmation after local validation,
not as the inner-loop test environment.

Build the image from the project root:

```bash
docker build -t leanecon .
```

Run the app with your Mistral API key:

```bash
docker run -p 8000:8000 \
  -e MISTRAL_API_KEY=your_key_here \
  -v "$(pwd)/.state:/app/state" \
  leanecon
```

Then open `http://localhost:8000/docs`. A lightweight health endpoint is
available at `http://localhost:8000/health`.

For local parity with the active Railway listener port, you can also run:

```bash
docker run -p 8080:8080 \
  -e PORT=8080 \
  -e MISTRAL_API_KEY=your_key_here \
  -v "$(pwd)/.state:/app/state" \
  leanecon
```

Then open `http://localhost:8080/docs`.

## What the image includes

- Python 3.11
- elan + Lean 4.28.0
- the repo-owned `scripts/run_lean_lsp_mcp.sh` launcher for `lean-lsp-mcp`
- a Docker-installed `lean-lsp-mcp` binary, so runtime startup does not depend
  on fetching the tool from PyPI
- Mathlib cache bootstrap via `lake exe cache get`
- A prebuilt `lean_workspace/` via `lake build`
- Python dependencies from `requirements.txt`
- FastAPI served by Uvicorn on port `8000`

## Railway Runtime

Treat Railway port selection as a deployment concern, not a code-path change.
The container still defaults to `8000` locally via `${PORT:-8000}`, but the
active Railway deployment on 2026-03-25 expected `PORT=8080`.

Release checks for Railway should confirm all three of these:

- the service boots with `PORT=8080`
- `/health` responds on that port
- `/app/scripts/run_lean_lsp_mcp.sh` exists and is executable inside the image

The CI Docker job now performs that validation against the built image before a
change can merge.

## Runtime notes

- `MISTRAL_API_KEY` must be provided at runtime.
- `LEANECON_STATE_DIR` defaults to `/app/state` inside the image.
- The image does not bake a real `.env` file into the container.
- The image exposes port `8000` and starts `uvicorn src.api:app` on
  `${PORT:-8000}`. That keeps local Docker defaults on `8000`, but Railway may
  still inject a different runtime `PORT` value.
- On Railway, trust the deploy log over the Docker fallback. On 2026-03-25, the
  active deployment came up on `0.0.0.0:8080`, and the public domain only
  recovered after its target port was changed to `8080` to match.
- If you see an edge `502`, first check the deploy log listener port and make
  the Public Networking target port match it before changing application code.
- Verification still happens locally inside the container with the Lean toolchain.
- Mount `/app/state` if you want the verified-result cache and JSONL run log to
  persist across container restarts.
- Benchmark snapshots are bundled into `/app/benchmarks/snapshots` at build
  time, and runtime reads prefer `/app/state/benchmarks/snapshots` when
  `LEANECON_STATE_DIR` is set. That means `/api/v1/benchmarks/latest` can work
  immediately after deploy while still allowing fresher mounted-state snapshots
  to override the baked-in copy.
- The image build still runs `lake build` to warm the workspace and precompile
  the default `LeanEcon` library target.
- The first image build can take a while because Lean and Mathlib artifacts must
  be fetched and compiled into the image.
- This is a Docker deployment path, not a serverless one. The app is not a fit
  for platforms that do not provide the required Lean toolchain and local build
  workflow.

## Environment Variables Used At Runtime

The current v1 runtime uses these environment variables:

- Required runtime secret:
  `MISTRAL_API_KEY`
- Container listener selection:
  `PORT` via the container startup command
- Python state/config:
  `LEANECON_STATE_DIR`
- Model/config fingerprinting:
  `LEANECON_MODEL`, `LEANECON_CONFIG_VERSION`
- Formalizer retrieval tuning:
  `LEANECON_ENABLE_FORMALIZATION_MCP_SEARCH`,
  `LEANECON_FORMALIZATION_MCP_SEARCH_TIMEOUT_SECONDS`,
  `LEANECON_FORMALIZATION_MCP_SEARCH_QUERIES`,
  `LEANECON_FORMALIZATION_AUTO_PREAMBLES`,
  `LEANECON_FORMALIZATION_MCP_SEARCH_CACHE_LIMIT`
- MCP runtime tuning:
  `LEANECON_MCP_STARTUP_TIMEOUT_SECONDS`,
  `LEANECON_MCP_TOOL_TIMEOUT_SECONDS`,
  `LEANECON_FORMALIZATION_MCP_COOLDOWN_SECONDS`
- Telemetry cost assumptions:
  `LEANECON_LLM_INPUT_USD_PER_1K_TOKENS`,
  `LEANECON_LLM_OUTPUT_USD_PER_1K_TOKENS`,
  `LEANECON_LLM_STRESS_MULTIPLIER`

The formalizer-side MCP toggle currently uses the same
`LEANECON_ENABLE_FORMALIZATION_MCP_SEARCH` flag for both prompt-time retrieval
and runtime retrieval gating.
