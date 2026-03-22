FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/root/.elan/bin:${PATH}"

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

COPY lean_workspace ./lean_workspace
RUN cd lean_workspace && lake exe cache get && lake build

COPY src ./src
COPY docs ./docs
COPY README.md ./README.md
RUN mkdir -p outputs logs

EXPOSE 8000

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]
