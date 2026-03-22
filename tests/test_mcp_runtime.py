"""Tests for src/mcp_runtime.py."""

from __future__ import annotations

from pathlib import Path

import pytest

import mcp_runtime


def test_build_stdio_params_uses_repo_launcher() -> None:
    params = mcp_runtime.build_lean_lsp_stdio_params()

    assert params.command.endswith("scripts/run_lean_lsp_mcp.sh")
    assert params.args == ["--transport", "stdio"]
    assert Path(params.cwd) == mcp_runtime.LEAN_WORKSPACE


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
