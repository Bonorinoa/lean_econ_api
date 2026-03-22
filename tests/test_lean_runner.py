"""Tests for src/lean_runner.py."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import lean_runner


class _FakeSession:
    def __init__(self, result):
        self._result = result

    async def call_tool(self, name: str, arguments: dict):
        assert name in {"lean_run_code", "lean_verify"}
        assert isinstance(arguments, dict)
        return self._result


class _FakeSessionContext:
    def __init__(self, result):
        self._result = result

    async def __aenter__(self):
        return _FakeSession(self._result)

    async def __aexit__(self, exc_type, exc, tb):
        return False


def test_extract_text_and_parse_structured() -> None:
    result = SimpleNamespace(content=[{"text": '{"success": true}'}])
    assert lean_runner._extract_text(result) == '{"success": true}'
    assert lean_runner._parse_structured('{"success": true}') == {"success": True}
    assert lean_runner._parse_structured("not-json") == {}


def test_run_code_filters_sorry_only_errors(monkeypatch) -> None:
    payload = {
        "success": False,
        "diagnostics": [
            {"severity": "warning", "message": "declaration uses `sorry`"},
        ],
    }
    result = SimpleNamespace(isError=False, content=[{"text": json.dumps(payload)}])
    monkeypatch.setattr(lean_runner, "open_lean_mcp_session", lambda: _FakeSessionContext(result))

    output = asyncio.run(lean_runner._run_code_async("import Mathlib"))

    assert output["valid"] is True
    assert output["errors"] == []
    assert output["warnings"] == ["declaration uses `sorry`"]


def test_run_code_raises_on_mcp_error(monkeypatch) -> None:
    result = SimpleNamespace(isError=True, content=[])
    monkeypatch.setattr(lean_runner, "open_lean_mcp_session", lambda: _FakeSessionContext(result))

    with pytest.raises(RuntimeError):
        asyncio.run(lean_runner._run_code_async("import Mathlib"))


def test_verify_axioms_normalizes_output(monkeypatch) -> None:
    payload = {
        "axioms": ["Classical.choice", "propext"],
        "warnings": [],
    }
    result = SimpleNamespace(isError=False, content=[{"text": json.dumps(payload)}])
    monkeypatch.setattr(lean_runner, "open_lean_mcp_session", lambda: _FakeSessionContext(result))

    output = asyncio.run(lean_runner._verify_axioms_async("/tmp/demo.lean", "demo"))

    assert output["sound"] is True
    assert output["nonstandard_axioms"] == []
    assert output["standard_axioms"] == ["Classical.choice", "propext"]


def test_extract_theorem_name() -> None:
    assert lean_runner.extract_theorem_name("theorem demo : True := by trivial") == "demo"
