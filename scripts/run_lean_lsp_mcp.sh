#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNTIME_ROOT="${LEANECON_MCP_RUNTIME_ROOT:-${PROJECT_ROOT}/.tmp/lean-lsp-mcp}"

mkdir -p \
  "${RUNTIME_ROOT}/home" \
  "${RUNTIME_ROOT}/cache" \
  "${RUNTIME_ROOT}/data" \
  "${RUNTIME_ROOT}/state"

export HOME="${RUNTIME_ROOT}/home"
export XDG_CACHE_HOME="${RUNTIME_ROOT}/cache"
export XDG_DATA_HOME="${RUNTIME_ROOT}/data"
export XDG_STATE_HOME="${RUNTIME_ROOT}/state"
export UV_CACHE_DIR="${RUNTIME_ROOT}/cache/uv"

exec uvx lean-lsp-mcp "$@"
