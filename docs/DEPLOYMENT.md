# LeanEcon Deployment

LeanEcon must run with local Lean tooling available because final verification
depends on `lake build` inside `lean_workspace/`.

## Docker

Build the image from the project root:

```bash
docker build -t leanecon .
```

Run the app with your Mistral API key:

```bash
docker run -p 8000:8000 -e MISTRAL_API_KEY=your_key_here leanecon
```

Then open `http://localhost:8000/docs`. A lightweight health endpoint is
available at `http://localhost:8000/health`.

## What the image includes

- Python 3.11
- elan + Lean 4.28.0
- `uv` for launching `lean-lsp-mcp` via `uvx`
- Mathlib cache bootstrap via `lake exe cache get`
- A prebuilt `lean_workspace/` via `lake build`
- Python dependencies from `requirements.txt`
- FastAPI served by Uvicorn on port `8000`

## Runtime notes

- `MISTRAL_API_KEY` must be provided at runtime.
- The image does not bake a real `.env` file into the container.
- The image exposes port `8000` and starts `uvicorn src.api:app`.
- Verification still happens locally inside the container with `lake build`.
- The first image build can take a while because Lean and Mathlib artifacts must
  be fetched and compiled into the image.
- This is a Docker deployment path, not a serverless one. The app is not a fit
  for platforms that do not provide the required Lean toolchain and local build
  workflow.
