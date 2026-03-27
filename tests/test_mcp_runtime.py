"""Tests for src/mcp_runtime.py."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import mcp_runtime


def test_build_stdio_params_uses_repo_launcher() -> None:
    params = mcp_runtime.build_lean_lsp_stdio_params()

    assert params.command.endswith("scripts/run_lean_lsp_mcp.sh")
    assert params.args == ["--transport", "stdio"]
    assert Path(params.cwd) == mcp_runtime.LEAN_WORKSPACE
    assert params.env["LEANECON_MCP_RUNTIME_ROOT"].endswith(".tmp/lean-lsp-mcp")


def test_lean_workspace_relative_path() -> None:
    path = mcp_runtime.LEAN_WORKSPACE / "LeanEcon" / "McpSmoke.lean"
    assert mcp_runtime.lean_workspace_relative_path(path) == "LeanEcon/McpSmoke.lean"

    with pytest.raises(ValueError):
        mcp_runtime.lean_workspace_relative_path(Path("/tmp/outside.lean"))


def test_parse_diagnostics_and_sorry_warning() -> None:
    errors, warnings = mcp_runtime.parse_diagnostics(
        {
            "result": {
                "items": [
                    {"severity": "error", "message": "bad tactic", "line": 7},
                    {"severity": "warning", "message": "declaration uses `sorry`"},
                ]
            }
        }
    )

    assert errors == ["line 7: bad tactic"]
    assert warnings == ["declaration uses `sorry`"]
    assert mcp_runtime.has_sorry_warning(warnings) is True


def test_missing_run_context_hint_mentions_current_venv() -> None:
    exc = ModuleNotFoundError("missing-module")
    assert "./leanEconAPI_venv/bin/python" in mcp_runtime._missing_run_context_hint(exc)


def test_build_stdio_params_respects_custom_runtime_root(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LEANECON_MCP_RUNTIME_ROOT", str(tmp_path / "mcp-runtime"))

    params = mcp_runtime.build_lean_lsp_stdio_params()

    assert params.env["LEANECON_MCP_RUNTIME_ROOT"] == str(tmp_path / "mcp-runtime")


def test_mcp_startup_failure_message_mentions_local_binary_and_uvx_fallback() -> None:
    message = mcp_runtime._mcp_startup_failure_message("dns failure")

    assert "lean-lsp-mcp" in message
    assert "uvx" in message
    assert "dns failure" in message


def test_query_lean_state_raises_runtime_error_on_tool_call_timeout(monkeypatch) -> None:
    """A slow tool call must raise RuntimeError with an actionable message, not hang."""
    monkeypatch.setattr(mcp_runtime, "MCP_TOOL_TIMEOUT_SECONDS", 0.01)

    class _SlowSession:
        async def call_tool(self, *_args, **_kwargs):
            await asyncio.sleep(5)

    @asynccontextmanager
    async def _fake_mcp_session():
        yield _SlowSession()

    with patch.object(mcp_runtime, "open_lean_mcp_session", _fake_mcp_session):
        with pytest.raises(RuntimeError, match="timed out"):
            asyncio.run(mcp_runtime.query_lean_state("LeanEcon/Fake.lean", 1))


def test_formalization_mcp_status_circuit_breaker_round_trip() -> None:
    mcp_runtime.reset_formalization_mcp_status()

    allowed, reason = mcp_runtime.formalization_mcp_available()
    assert allowed is True
    assert reason is None

    mcp_runtime.mark_formalization_mcp_failure(
        "lean_run_code bootstrap failed",
        capability=mcp_runtime.FORMALIZATION_MCP_CAPABILITY_VALIDATION,
    )
    allowed, reason = mcp_runtime.formalization_mcp_available(
        capability=mcp_runtime.FORMALIZATION_MCP_CAPABILITY_VALIDATION
    )
    assert allowed is False
    assert "bootstrap failed" in (reason or "")

    retrieval_allowed, retrieval_reason = mcp_runtime.formalization_mcp_available(
        capability=mcp_runtime.FORMALIZATION_MCP_CAPABILITY_RETRIEVAL
    )
    assert retrieval_allowed is True
    assert retrieval_reason is None

    mcp_runtime.reset_formalization_mcp_status()
    allowed, reason = mcp_runtime.formalization_mcp_available()
    assert allowed is True
    assert reason is None


def test_formalization_retrieval_circuit_breaker_is_independent() -> None:
    mcp_runtime.reset_formalization_mcp_status()

    mcp_runtime.mark_formalization_mcp_failure(
        "lean_local_search bootstrap failed",
        capability=mcp_runtime.FORMALIZATION_MCP_CAPABILITY_RETRIEVAL,
    )

    allowed, reason = mcp_runtime.formalization_mcp_available(
        capability=mcp_runtime.FORMALIZATION_MCP_CAPABILITY_RETRIEVAL
    )
    assert allowed is False
    assert "lean_local_search bootstrap failed" in (reason or "")

    validation_allowed, validation_reason = mcp_runtime.formalization_mcp_available(
        capability=mcp_runtime.FORMALIZATION_MCP_CAPABILITY_VALIDATION
    )
    assert validation_allowed is True
    assert validation_reason is None


def test_prime_lean_mcp_session_uses_mcp_smoke_file() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    class _PrimingSession:
        async def call_tool(self, name: str, arguments: dict[str, str]):
            calls.append((name, arguments))
            return SimpleNamespace(isError=False, content=[{"text": "{}"}])

    asyncio.run(mcp_runtime.prime_lean_mcp_session(_PrimingSession()))

    assert calls == [
        (
            "lean_file_outline",
            {
                "file_path": "LeanEcon/McpSmoke.lean",
                "max_declarations": "1",
            },
        )
    ]


def test_bootstrap_formalization_validation_session_runs_project_queries() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _BootstrapSession:
        async def call_tool(self, name: str, arguments: dict[str, object]):
            calls.append((name, arguments))
            return SimpleNamespace(isError=False, content=[{"text": "{}"}])

    asyncio.run(mcp_runtime.bootstrap_formalization_validation_session(_BootstrapSession()))

    assert calls == [
        (
            "lean_file_outline",
            {
                "file_path": "LeanEcon/McpSmoke.lean",
                "max_declarations": "1",
            },
        ),
        (
            "lean_diagnostic_messages",
            {"file_path": "LeanEcon/McpSmoke.lean"},
        ),
        (
            "lean_goal",
            {"file_path": "LeanEcon/McpSmoke.lean", "line": 4},
        ),
    ]
