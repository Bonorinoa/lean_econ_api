FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV LEANECON_STATE_DIR=/app/state
ENV PATH="/root/.local/bin:/root/.elan/bin:${PATH}"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    git \
    libgmp-dev \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf \
    | sh -s -- -y --default-toolchain none
RUN elan default leanprover/lean4:v4.28.0

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
RUN python -m pip install --no-cache-dir uv
RUN uv tool install lean-lsp-mcp

COPY lean_workspace ./lean_workspace
RUN cd lean_workspace && lake exe cache get && lake build

COPY scripts ./scripts
COPY src ./src
COPY benchmarks ./benchmarks
COPY docs ./docs
COPY README.md ./README.md
RUN chmod +x /app/scripts/run_lean_lsp_mcp.sh
RUN mkdir -p outputs logs /app/state /app/state/benchmarks/snapshots /app/state/benchmarks/reports

EXPOSE 8000

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
