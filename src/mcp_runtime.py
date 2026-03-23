"""
mcp_runtime.py

Helpers for LeanEcon's MCP-backed prover work.

This module centralizes the local lean-lsp-mcp stdio launch recipe,
Mistral RunContext setup, and shared MCP query helpers.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from mistralai.extra.mcp.stdio import MCPClientSTDIO

# Suppress noisy "Failed to parse JSONRPC message" warnings from the MCP stdio
# client. These fire whenever `lake build` writes plain-text progress messages
# (e.g. "Current branch: HEAD", "Using cache (Azure) from...") to stdout,
# which the MCP client tries to parse as JSON-RPC. The messages are harmless —
# actual JSON-RPC responses still get through — but they create massive log
# noise during evaluation runs. The root cause is upstream in lean-lsp-mcp
# (should redirect Lake's stdout to stderr in stdio transport mode).
logging.getLogger("mcp.client.stdio").setLevel(logging.CRITICAL)

if TYPE_CHECKING:
    from mistralai.extra.run.context import RunContext


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEAN_WORKSPACE = PROJECT_ROOT / "lean_workspace"
LEAN_LSP_MCP_COMMAND = str(PROJECT_ROOT / "scripts" / "run_lean_lsp_mcp.sh")
LEAN_LSP_MCP_ARGS = ["--transport", "stdio"]
LEAN_MCP_CLIENT_NAME = "lean-lsp-mcp"
DEFAULT_MCP_RUNTIME_ROOT = str(PROJECT_ROOT / ".tmp" / "lean-lsp-mcp")
MCP_STARTUP_TIMEOUT_SECONDS = float(os.environ.get("LEANECON_MCP_STARTUP_TIMEOUT_SECONDS", "30"))
MCP_TOOL_TIMEOUT_SECONDS = float(os.environ.get("LEANECON_MCP_TOOL_TIMEOUT_SECONDS", "60"))
FORMALIZATION_MCP_COOLDOWN_SECONDS = float(
    os.environ.get("LEANECON_FORMALIZATION_MCP_COOLDOWN_SECONDS", "120")
)
_FORMALIZATION_MCP_DISABLED_UNTIL = 0.0
_FORMALIZATION_MCP_LAST_FAILURE: str | None = None

# NOTE (2026-03-21): we intentionally create a fresh MCPClientSTDIO for each
# RunContext. Local probing showed that re-registering the same client instance
# with a second sequential RunContext raises ClosedResourceError because
# `RunContext.register_mcp_client()` initializes the client against the
# context-owned AsyncExitStack and `RunContext.__aexit__()` closes that stack,
# then calls `mcp_client.aclose()`. Until the SDK offers a detach/rebind-safe
# lifecycle, a warm MCP client pool is not reliable here.

# Match the existing repo convention of loading .env from the project root.
load_dotenv(PROJECT_ROOT / ".env")


def _mcp_startup_failure_message(details: str) -> str:
    return (
        "Failed to start lean-lsp-mcp. The launcher now prefers a locally installed "
        "`lean-lsp-mcp` binary and falls back to `uvx lean-lsp-mcp` only when no "
        "binary is present. In offline or DNS-restricted environments, install "
        "`lean-lsp-mcp` ahead of time or validate through the Docker image. "
        f"Underlying error: {details}"
    )


def reset_formalization_mcp_status() -> None:
    """Clear formalizer-side MCP cooldown state."""
    global _FORMALIZATION_MCP_DISABLED_UNTIL, _FORMALIZATION_MCP_LAST_FAILURE
    _FORMALIZATION_MCP_DISABLED_UNTIL = 0.0
    _FORMALIZATION_MCP_LAST_FAILURE = None


def mark_formalization_mcp_failure(reason: str) -> None:
    """Open the formalizer MCP circuit breaker for a short cooldown window."""
    global _FORMALIZATION_MCP_DISABLED_UNTIL, _FORMALIZATION_MCP_LAST_FAILURE
    _FORMALIZATION_MCP_DISABLED_UNTIL = time.monotonic() + FORMALIZATION_MCP_COOLDOWN_SECONDS
    _FORMALIZATION_MCP_LAST_FAILURE = reason


def mark_formalization_mcp_success() -> None:
    """Clear any existing formalizer MCP cooldown after a successful tool call."""
    reset_formalization_mcp_status()


def formalization_mcp_available() -> tuple[bool, str | None]:
    """Return whether formalizer-side MCP helpers should currently run."""
    remaining = _FORMALIZATION_MCP_DISABLED_UNTIL - time.monotonic()
    if remaining > 0:
        reason = _FORMALIZATION_MCP_LAST_FAILURE or "recent MCP failure"
        return False, (
            "formalization MCP temporarily disabled after recent failure: "
            f"{reason} (retry in ~{int(remaining)}s)"
        )
    return True, None


def build_lean_lsp_stdio_params() -> StdioServerParameters:
    """
    Build the stdio launch configuration for the local Lean MCP server.

    The server must start from the Lean project root. Passing
    `--lean-project-path` caused the installed server to crash in this repo, so
    we rely on `cwd=lean_workspace/` instead.
    """
    if not LEAN_WORKSPACE.is_dir():
        raise FileNotFoundError(f"Lean workspace not found: {LEAN_WORKSPACE}")
    env = get_default_environment()
    env.update(os.environ)
    env.setdefault("LEANECON_MCP_RUNTIME_ROOT", DEFAULT_MCP_RUNTIME_ROOT)
    return StdioServerParameters(
        command=LEAN_LSP_MCP_COMMAND,
        args=list(LEAN_LSP_MCP_ARGS),
        cwd=str(LEAN_WORKSPACE),
        env=env,
    )


def lean_workspace_relative_path(path: Path) -> str:
    """Convert an absolute or relative path under `lean_workspace/` to MCP form."""
    resolved_path = path.resolve()
    resolved_workspace = LEAN_WORKSPACE.resolve()
    try:
        return str(resolved_path.relative_to(resolved_workspace))
    except ValueError as exc:
        raise ValueError(f"Path is outside lean_workspace/: {path}") from exc


@asynccontextmanager
async def open_lean_mcp_session() -> AsyncIterator[ClientSession]:
    """Open an initialized raw MCP client session for lean-lsp-mcp."""
    params = build_lean_lsp_stdio_params()
    try:
        async with AsyncExitStack() as stack:
            read_stream, write_stream = await asyncio.wait_for(
                stack.enter_async_context(stdio_client(params)),
                timeout=MCP_STARTUP_TIMEOUT_SECONDS,
            )
            session = await asyncio.wait_for(
                stack.enter_async_context(ClientSession(read_stream, write_stream)),
                timeout=MCP_STARTUP_TIMEOUT_SECONDS,
            )
            await asyncio.wait_for(session.initialize(), timeout=MCP_STARTUP_TIMEOUT_SECONDS)
            yield session
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            _mcp_startup_failure_message(
                f"timed out after {MCP_STARTUP_TIMEOUT_SECONDS:.0f}s during MCP session startup"
            )
        ) from exc
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(_mcp_startup_failure_message(str(exc))) from exc


def build_mistral_mcp_client() -> MCPClientSTDIO:
    """Build the Mistral MCP client wrapper for the local Lean MCP server."""
    return MCPClientSTDIO(
        stdio_params=build_lean_lsp_stdio_params(),
        name=LEAN_MCP_CLIENT_NAME,
    )


def _missing_run_context_hint(exc: ModuleNotFoundError) -> str:
    missing_name = exc.name or "an optional dependency"
    return (
        "Mistral RunContext is unavailable because "
        f"`{missing_name}` is not installed in the project venv. "
        "Run `./leanEconAPI_venv/bin/python -m pip install -r requirements.txt` "
        "and retry."
    )


@asynccontextmanager
async def open_mistral_run_context(
    model: str | None = None,
) -> AsyncIterator["RunContext"]:
    """
    Open a Mistral RunContext with lean-lsp-mcp already registered.

    The RunContext import is intentionally lazy so Phase 0-1 can surface a
    clear install hint if the optional agents dependencies are incomplete.

    A fresh MCP client is registered on every entry. Reusing a closed
    MCPClientSTDIO across sequential RunContexts currently fails with
    ClosedResourceError in the Mistral SDK.
    """
    try:
        from mistralai.extra.run.context import RunContext
    except ModuleNotFoundError as exc:
        raise RuntimeError(_missing_run_context_hint(exc)) from exc

    async with RunContext(model=model) as run_ctx:
        try:
            await asyncio.wait_for(
                run_ctx.register_mcp_client(build_mistral_mcp_client()),
                timeout=MCP_STARTUP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                _mcp_startup_failure_message(
                    "timed out after "
                    f"{MCP_STARTUP_TIMEOUT_SECONDS:.0f}s while registering MCP tools"
                )
            ) from exc
        except Exception as exc:
            raise RuntimeError(_mcp_startup_failure_message(str(exc))) from exc
        yield run_ctx


# ---------------------------------------------------------------------------
# MCP query helpers
# ---------------------------------------------------------------------------


def parse_diagnostics(diagnostics_structured: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Parse structured MCP diagnostics into (errors, warnings) string lists.

    Each item is formatted as "line N: message" when a line number is present.
    """
    result = diagnostics_structured.get("result", {})
    items = result.get("items", [])
    errors: list[str] = []
    warnings: list[str] = []
    for item in items:
        message = item.get("message", "")
        line = item.get("line")
        prefix = f"line {line}: " if line else ""
        if item.get("severity") == "error":
            errors.append(prefix + message)
        elif item.get("severity") == "warning":
            warnings.append(prefix + message)
    return errors, warnings


def has_sorry_warning(warnings: list[str]) -> bool:
    """Check if any warning mentions sorry."""
    return any("sorry" in w.lower() for w in warnings)


async def query_lean_state(file_path: str, goal_line: int) -> dict[str, Any]:
    """
    Query diagnostics and goal state for a Lean file via a fresh MCP session.

    Opens a temporary MCP session, queries both diagnostics and goals,
    parses the results, and returns a structured dict.

    Args:
        file_path: Lean file path relative to lean_workspace/
            (e.g. "LeanEcon/AgenticProof_ab12cd34ef56.lean")
        goal_line: Line number to query goals at (1-indexed, typically the `:= by` line)

    Returns:
        dict with keys:
          - errors (list[str]): Parsed error messages
          - warnings (list[str]): Parsed warning messages
          - goals_after (list[str]): Remaining goals (empty if proof is complete)
          - has_sorry (bool): True if any warning mentions sorry
          - raw_diagnostics (dict): Raw structured diagnostics payload
          - raw_goal (dict): Raw structured goal payload
    """
    try:
        async with open_lean_mcp_session() as session:
            diagnostics = await asyncio.wait_for(
                session.call_tool(
                    "lean_diagnostic_messages",
                    {"file_path": file_path},
                ),
                timeout=MCP_TOOL_TIMEOUT_SECONDS,
            )
            if getattr(diagnostics, "isError", False):
                raise RuntimeError("lean_diagnostic_messages returned an MCP error")

            goal = await asyncio.wait_for(
                session.call_tool(
                    "lean_goal",
                    {"file_path": file_path, "line": goal_line},
                ),
                timeout=MCP_TOOL_TIMEOUT_SECONDS,
            )
            if getattr(goal, "isError", False):
                raise RuntimeError("lean_goal returned an MCP error")
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"MCP tool call timed out after {MCP_TOOL_TIMEOUT_SECONDS:.0f}s. "
            "Increase LEANECON_MCP_TOOL_TIMEOUT_SECONDS if Lean type-checking is slow."
        ) from exc

    diag_structured = getattr(diagnostics, "structuredContent", None) or {}
    goal_structured = getattr(goal, "structuredContent", None) or {}
    goals_after = goal_structured.get("goals_after", [])
    if not isinstance(goals_after, list):
        goals_after = []

    errors, warnings = parse_diagnostics(diag_structured)

    return {
        "errors": errors,
        "warnings": warnings,
        "goals_after": goals_after,
        "has_sorry": has_sorry_warning(warnings),
        "raw_diagnostics": diag_structured,
        "raw_goal": goal_structured,
    }
