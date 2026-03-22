"""Tests for src/mcp_smoke_test.py."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import mcp_smoke_test


def test_find_expected_diagnostic_and_goal_extraction() -> None:
    items = [
        {
            "severity": "error",
            "line": mcp_smoke_test.EXPECTED_DIAGNOSTIC_LINE,
            "message": f"{mcp_smoke_test.EXPECTED_DIAGNOSTIC_SUBSTRING} in fixture",
        }
    ]
    matched = mcp_smoke_test._find_expected_diagnostic(items)
    assert matched["line"] == mcp_smoke_test.EXPECTED_DIAGNOSTIC_LINE

    goal_result = SimpleNamespace(
        structuredContent={"goals_after": [mcp_smoke_test.EXPECTED_GOAL_SUBSTRING]}
    )
    assert mcp_smoke_test._extract_goals_after(goal_result) == [
        mcp_smoke_test.EXPECTED_GOAL_SUBSTRING
    ]


def test_main_success(capsys) -> None:
    diagnostics = SimpleNamespace(
        structuredContent={
            "result": {
                "items": [
                    {
                        "severity": "error",
                        "line": mcp_smoke_test.EXPECTED_DIAGNOSTIC_LINE,
                        "message": f"{mcp_smoke_test.EXPECTED_DIAGNOSTIC_SUBSTRING} in fixture",
                    }
                ]
            }
        }
    )
    goal = SimpleNamespace(
        structuredContent={"goals_after": [f"goal\n{mcp_smoke_test.EXPECTED_GOAL_SUBSTRING}"]}
    )

    async def fake_verify_run_context_tools() -> list[str]:
        return sorted(mcp_smoke_test.REQUIRED_TOOLS)

    async def fake_run_raw_queries():
        return diagnostics, goal

    with patch.object(mcp_smoke_test, "_ensure_api_key"):
        with patch.object(mcp_smoke_test, "_ensure_fixture_file"):
            with patch.object(
                mcp_smoke_test,
                "_verify_run_context_tools",
                side_effect=fake_verify_run_context_tools,
            ):
                with patch.object(
                    mcp_smoke_test, "_run_raw_queries", side_effect=fake_run_raw_queries
                ):
                    exit_code = mcp_smoke_test.main()

    assert exit_code == 0
    assert "Smoke test PASSED" in capsys.readouterr().out
