# LeanEcon Deployment

LeanEcon must run with local Lean tooling available because final verification
depends on the local Lean toolchain inside `lean_workspace/`. Runtime verify
jobs use isolated per-run temp files compiled with `lake env lean`.

## Docker

Treat Docker as the primary pre-deploy validation target. Railway rebuilds take
long enough that they should be used for confirmation after local validation,
not as the inner-loop test environment.

Build the image from the project root:

```bash
docker build -t leanecon .
```

Run the app with your Mistral API key:

```bash
docker run -p 8000:8080 \
  -e MISTRAL_API_KEY=your_key_here \
  -v "$(pwd)/.state:/app/state" \
  leanecon
```

Then open `http://localhost:8000/docs`. A lightweight health endpoint is
available at `http://localhost:8000/health`.

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

## Runtime notes

- `MISTRAL_API_KEY` must be provided at runtime.
- `LEANECON_STATE_DIR` defaults to `/app/state` inside the image.
- The image does not bake a real `.env` file into the container.
- The image exposes port `8080` and starts `uvicorn src.api:app` on
  `${PORT:-8080}`, so Railway-style injected ports are honored automatically.
- On Railway, make sure the public domain target port matches the container
  listener. If you see an edge `502` with logs showing Uvicorn on `:8080`, set
  the service target port to `8080` or clear any stale manual target-port
  override.
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
