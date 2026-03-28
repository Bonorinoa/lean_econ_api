"""
mcp_smoke_test.py

Phase 0-1 smoke test for LeanEcon's MCP plumbing.

Checks that:
  1. `.env` loads and exposes `MISTRAL_API_KEY`
  2. Mistral RunContext can register Lean MCP tools
  3. Raw MCP diagnostics and goal queries succeed against a dedicated fixture
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from dotenv import load_dotenv

from mcp_runtime import (
    LEAN_WORKSPACE,
    MCP_TOOL_TIMEOUT_SECONDS,
    PROJECT_ROOT,
    lean_workspace_relative_path,
    open_lean_mcp_session,
    open_mistral_run_context,
    prime_lean_mcp_session,
)
from model_config import LEANSTRAL_MODEL

FIXTURE_PATH = LEAN_WORKSPACE / "LeanEcon" / "McpSmoke.lean"
TARGET_FILE = lean_workspace_relative_path(FIXTURE_PATH)
GOAL_QUERY_LINE = 4
EXPECTED_DIAGNOSTIC_LINE = 5
EXPECTED_DIAGNOSTIC_SUBSTRING = "Tactic `rfl` failed"
EXPECTED_GOAL_SUBSTRING = "⊢ x = y"
REQUIRED_TOOLS = {"lean_diagnostic_messages", "lean_goal"}
SMOKE_MCP_TOOL_TIMEOUT_SECONDS = max(
    MCP_TOOL_TIMEOUT_SECONDS,
    float(os.environ.get("LEANECON_MCP_SMOKE_TOOL_TIMEOUT_SECONDS", "180")),
)


def _print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def _ensure_api_key() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    if not os.environ.get("MISTRAL_API_KEY"):
        raise RuntimeError("MISTRAL_API_KEY is missing after loading .env")
    print("MISTRAL_API_KEY detected")


def _ensure_fixture_file() -> None:
    if not FIXTURE_PATH.is_file():
        raise RuntimeError(f"MCP smoke-test fixture is missing: {FIXTURE_PATH}")
    print(f"Fixture detected: {FIXTURE_PATH}")


def _tool_names(run_ctx) -> list[str]:
    return sorted(tool.function.name for tool in run_ctx.get_tools())


def _diagnostic_items(diagnostics_result) -> list[dict]:
    structured = getattr(diagnostics_result, "structuredContent", None) or {}
    result = structured.get("result", {})
    items = result.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError("Diagnostics payload did not contain an `items` list")
    return items


def _find_expected_diagnostic(items: list[dict]) -> dict:
    for item in items:
        if (
            item.get("severity") == "error"
            and item.get("line") == EXPECTED_DIAGNOSTIC_LINE
            and EXPECTED_DIAGNOSTIC_SUBSTRING in item.get("message", "")
        ):
            return item
    raise RuntimeError("Did not find the expected MCP diagnostic shape in the fixture file")


def _extract_goals_after(goal_result) -> list[str]:
    structured = getattr(goal_result, "structuredContent", None) or {}
    goals_after = structured.get("goals_after", [])
    if not isinstance(goals_after, list):
        raise RuntimeError("Goal payload did not contain a `goals_after` list")
    return goals_after


async def _verify_run_context_tools() -> list[str]:
    async with open_mistral_run_context(model=LEANSTRAL_MODEL) as run_ctx:
        tool_names = _tool_names(run_ctx)
        missing = sorted(REQUIRED_TOOLS - set(tool_names))
        if missing:
            raise RuntimeError(f"RunContext registered Lean tools incompletely: {missing}")
        return tool_names


async def _run_raw_queries() -> tuple[object, object]:
    try:
        async with open_lean_mcp_session() as session:
            await prime_lean_mcp_session(
                session,
                timeout_seconds=SMOKE_MCP_TOOL_TIMEOUT_SECONDS,
            )
            diagnostics = await asyncio.wait_for(
                session.call_tool(
                    "lean_diagnostic_messages",
                    {"file_path": TARGET_FILE},
                ),
                timeout=SMOKE_MCP_TOOL_TIMEOUT_SECONDS,
            )
            if getattr(diagnostics, "isError", False):
                raise RuntimeError("lean_diagnostic_messages returned an MCP error")

            goal = await asyncio.wait_for(
                session.call_tool(
                    "lean_goal",
                    {"file_path": TARGET_FILE, "line": GOAL_QUERY_LINE},
                ),
                timeout=SMOKE_MCP_TOOL_TIMEOUT_SECONDS,
            )
            if getattr(goal, "isError", False):
                raise RuntimeError("lean_goal returned an MCP error")

            return diagnostics, goal
    except asyncio.TimeoutError as exc:
        raise RuntimeError(
            f"MCP tool call timed out after {SMOKE_MCP_TOOL_TIMEOUT_SECONDS:.0f}s. "
            "Increase LEANECON_MCP_SMOKE_TOOL_TIMEOUT_SECONDS if cold Lean MCP "
            "startup is slower in this environment."
        ) from exc


async def _main() -> int:
    _print_header("LeanEcon MCP Smoke Test")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Lean workspace: {LEAN_WORKSPACE}")
    print(f"Target file: {TARGET_FILE}")

    _print_header("Environment")
    _ensure_api_key()
    _ensure_fixture_file()

    _print_header("RunContext Registration")
    tool_names = await _verify_run_context_tools()
    print(f"Registered {len(tool_names)} tools")
    print(", ".join(name for name in tool_names if name in REQUIRED_TOOLS))

    _print_header("Raw MCP Queries")
    diagnostics, goal = await _run_raw_queries()
    diagnostic_items = _diagnostic_items(diagnostics)
    matched_diagnostic = _find_expected_diagnostic(diagnostic_items)
    goals_after = _extract_goals_after(goal)
    if not goals_after:
        raise RuntimeError("Goal query succeeded but `goals_after` was empty")
    if EXPECTED_GOAL_SUBSTRING not in goals_after[0]:
        raise RuntimeError("Goal query returned an unexpected goal state")

    print(f"Diagnostics query succeeded for {TARGET_FILE}")
    print(
        "Matched expected diagnostic: "
        f"line {matched_diagnostic['line']} / {matched_diagnostic['severity']} / "
        f"{matched_diagnostic['message'].splitlines()[0]}"
    )
    print(f"Goal query line: {GOAL_QUERY_LINE}")
    print(f"First goal after: {goals_after[0].splitlines()[-1]}")

    diagnostics_structured = getattr(diagnostics, "structuredContent", None)
    goal_structured = getattr(goal, "structuredContent", None)

    print("\nMatched diagnostic payload:")
    print(json.dumps(matched_diagnostic, indent=2, ensure_ascii=False))

    print("\nDiagnostics structured payload:")
    print(json.dumps(diagnostics_structured, indent=2, ensure_ascii=False))

    print("\nGoal structured payload:")
    print(json.dumps(goal_structured, indent=2, ensure_ascii=False))

    print("\nSmoke test PASSED")
    return 0


def main() -> int:
    try:
        return asyncio.run(_main())
    except Exception as exc:
        print(f"\nSmoke test FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
