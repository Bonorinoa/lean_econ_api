"""Tests for src/lean_runner.py."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

import lean_runner
import mcp_runtime


@pytest.fixture(autouse=True)
def _reset_mcp_status():
    mcp_runtime.reset_formalization_mcp_status()
    yield
    mcp_runtime.reset_formalization_mcp_status()


class _FakeSession:
    def __init__(self, result):
        self._result = result

    async def call_tool(self, name: str, arguments: dict):
        assert name in {
            "lean_file_outline",
            "lean_diagnostic_messages",
            "lean_goal",
            "lean_run_code",
            "lean_verify",
        }
        assert isinstance(arguments, dict)
        if name in {"lean_file_outline", "lean_diagnostic_messages", "lean_goal"}:
            return SimpleNamespace(isError=False, content=[{"text": "{}"}])
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


def test_verify_axioms_times_out_slow_mcp_calls(monkeypatch) -> None:
    class _SlowSession:
        async def call_tool(self, name: str, arguments: dict):
            del name, arguments
            await asyncio.sleep(0.05)
            return SimpleNamespace(
                isError=False,
                content=[{"text": '{"axioms": [], "warnings": []}'}],
            )

    class _SlowSessionContext:
        async def __aenter__(self):
            return _SlowSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(lean_runner, "open_lean_mcp_session", lambda: _SlowSessionContext())
    monkeypatch.setattr(lean_runner, "MCP_TOOL_TIMEOUT_SECONDS", 0.001)

    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(lean_runner._verify_axioms_async("/tmp/demo.lean", "demo"))


def test_run_code_sync_wrapper_works_inside_running_event_loop(monkeypatch) -> None:
    async def fake_run_code_async(_: str) -> dict[str, object]:
        return {"valid": True, "errors": [], "warnings": [], "raw": "{}"}

    monkeypatch.setattr(lean_runner, "_run_code_async", fake_run_code_async)

    async def invoke() -> dict[str, object]:
        return lean_runner.run_code("import Mathlib")

    output = asyncio.run(invoke())

    assert output["valid"] is True
    assert output["errors"] == []


def test_verify_axioms_sync_wrapper_works_inside_running_event_loop(monkeypatch) -> None:
    async def fake_verify_axioms_async(_: str, __: str) -> dict[str, object]:
        return {
            "axioms": ["Classical.choice"],
            "standard_axioms": ["Classical.choice"],
            "nonstandard_axioms": [],
            "has_sorry_ax": False,
            "sound": True,
            "source_warnings": [],
        }

    monkeypatch.setattr(lean_runner, "_verify_axioms_async", fake_verify_axioms_async)

    async def invoke() -> dict[str, object]:
        return lean_runner.verify_axioms("/tmp/demo.lean", "demo")

    output = asyncio.run(invoke())

    assert output["sound"] is True
    assert output["standard_axioms"] == ["Classical.choice"]


def test_extract_theorem_name() -> None:
    assert lean_runner.extract_theorem_name("theorem demo : True := by trivial") == "demo"


def test_run_code_bootstraps_validation_session_before_run_code(monkeypatch) -> None:
    events: list[str] = []
    payload = {
        "success": True,
        "diagnostics": [
            {"severity": "warning", "message": "declaration uses `sorry`"},
        ],
    }

    class _RunCodeSession:
        async def call_tool(self, name: str, arguments: dict):
            events.append(name)
            assert isinstance(arguments, dict)
            if name == "lean_run_code":
                return SimpleNamespace(isError=False, content=[{"text": json.dumps(payload)}])
            return SimpleNamespace(isError=False, content=[{"text": "{}"}])

    class _RunCodeContext:
        async def __aenter__(self):
            return _RunCodeSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _bootstrap(session) -> None:
        events.append("bootstrap_start")
        await session.call_tool(
            "lean_diagnostic_messages",
            {"file_path": "LeanEcon/McpSmoke.lean"},
        )
        await session.call_tool(
            "lean_goal",
            {"file_path": "LeanEcon/McpSmoke.lean", "line": 4},
        )
        events.append("bootstrap_done")

    monkeypatch.setattr(lean_runner, "open_lean_mcp_session", lambda: _RunCodeContext())
    monkeypatch.setattr(lean_runner, "bootstrap_formalization_validation_session", _bootstrap)

    output = asyncio.run(lean_runner._run_code_async("import Mathlib"))

    assert output["valid"] is True
    assert events == [
        "bootstrap_start",
        "lean_diagnostic_messages",
        "lean_goal",
        "bootstrap_done",
        "lean_run_code",
    ]


def test_run_code_retries_once_after_project_path_bootstrap_failure(monkeypatch) -> None:
    calls = {"bootstrap": 0, "lean_run_code": 0}
    success_payload = {
        "success": True,
        "diagnostics": [
            {"severity": "warning", "message": "declaration uses `sorry`"},
        ],
    }

    class _RetrySession:
        async def call_tool(self, name: str, arguments: dict):
            assert isinstance(arguments, dict)
            if name == "lean_run_code":
                calls["lean_run_code"] += 1
                if calls["lean_run_code"] == 1:
                    return SimpleNamespace(
                        isError=True,
                        content=[
                            {
                                "text": (
                                    "Error executing tool lean_run_code: "
                                    "No valid Lean project path found. "
                                    "Run another tool first to set it up."
                                )
                            }
                        ],
                    )
                return SimpleNamespace(
                    isError=False,
                    content=[{"text": json.dumps(success_payload)}],
                )
            return SimpleNamespace(isError=False, content=[{"text": "{}"}])

    class _RetrySessionContext:
        async def __aenter__(self):
            return _RetrySession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _bootstrap(_session) -> None:
        calls["bootstrap"] += 1

    monkeypatch.setattr(lean_runner, "open_lean_mcp_session", lambda: _RetrySessionContext())
    monkeypatch.setattr(lean_runner, "bootstrap_formalization_validation_session", _bootstrap)

    output = asyncio.run(lean_runner._run_code_async("import Mathlib"))

    assert output["valid"] is True
    assert calls == {"bootstrap": 2, "lean_run_code": 2}


def test_run_code_circuit_breaker_skips_repeated_failures(monkeypatch) -> None:
    mcp_runtime.reset_formalization_mcp_status()
    calls = {"bootstrap": 0, "lean_run_code": 0}

    class _ProjectPathSession:
        async def call_tool(self, name: str, arguments: dict):
            assert isinstance(arguments, dict)
            if name != "lean_run_code":
                return SimpleNamespace(isError=False, content=[{"text": "{}"}])
            calls["lean_run_code"] += 1
            return SimpleNamespace(
                isError=True,
                content=[
                    {
                        "text": (
                            "Error executing tool lean_run_code: "
                            "No valid Lean project path found. Run another tool first to set it up."
                        )
                    }
                ],
            )

    class _ProjectPathContext:
        async def __aenter__(self):
            return _ProjectPathSession()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    async def _bootstrap(_session) -> None:
        calls["bootstrap"] += 1

    monkeypatch.setattr(lean_runner, "open_lean_mcp_session", lambda: _ProjectPathContext())
    monkeypatch.setattr(lean_runner, "bootstrap_formalization_validation_session", _bootstrap)

    with pytest.raises(RuntimeError, match="No valid Lean project path found"):
        asyncio.run(lean_runner._run_code_async("import Mathlib"))

    assert calls["bootstrap"] == 2
    assert calls["lean_run_code"] == 2

    with pytest.raises(RuntimeError, match="temporarily disabled"):
        asyncio.run(lean_runner._run_code_async("import Mathlib"))

    assert calls["lean_run_code"] == 2
    retrieval_allowed, retrieval_reason = mcp_runtime.formalization_mcp_available(
        capability=mcp_runtime.FORMALIZATION_MCP_CAPABILITY_RETRIEVAL
    )
    assert retrieval_allowed is True
    assert retrieval_reason is None
    mcp_runtime.reset_formalization_mcp_status()
