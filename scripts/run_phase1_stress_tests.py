"""
Run the Phase 1 agentic stress-test suite.

This script validates each raw Lean stress case with both lean-lsp-mcp and the
Lean compiler, then runs the isolated agentic pipeline and saves raw artifacts
plus an aggregate markdown report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from mcp_runtime import (  # noqa: E402
    LEAN_WORKSPACE,
    lean_workspace_relative_path,
    open_lean_mcp_session,
    parse_diagnostics,
)
from pipeline import run_pipeline  # noqa: E402

TEST_CASES = [
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "lean_advanced"
    / "test_04_water_extraction_dynamics.lean",
    PROJECT_ROOT
    / "tests"
    / "fixtures"
    / "lean_advanced"
    / "test_05_expected_utility_representation.lean",
    PROJECT_ROOT / "tests" / "fixtures" / "lean_advanced" / "test_06_advanced_optimization.lean",
]
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "phase1_stress"
SUMMARY_PATH = PROJECT_ROOT / "outputs" / "phase1_stress_test_results.md"
VALIDATION_DIR = LEAN_WORKSPACE / "LeanEcon" / "StressValidation"
PROOF_PATH = LEAN_WORKSPACE / "LeanEcon" / "Proof.lean"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the LeanEcon Phase 1 stress suite.")
    parser.add_argument(
        "--cases",
        nargs="*",
        default=None,
        help=(
            "Optional case filters. Match either the file stem "
            "(for example `test_04_water_extraction_dynamics`) or the full filename."
        ),
    )
    parser.add_argument(
        "--summary-path",
        default=str(SUMMARY_PATH),
        help="Optional markdown output path for the aggregate summary report.",
    )
    return parser.parse_args()


def _select_cases(case_filters: list[str] | None) -> list[Path]:
    if not case_filters:
        return list(TEST_CASES)

    requested = {item.strip() for item in case_filters if item.strip()}
    selected = [
        case_path
        for case_path in TEST_CASES
        if case_path.stem in requested or case_path.name in requested
    ]
    if not selected:
        raise SystemExit(
            "No stress cases matched the provided filters: " + ", ".join(sorted(requested))
        )
    return selected


def _goal_line(lean_code: str) -> int:
    for index, line in enumerate(lean_code.splitlines(), start=1):
        if ":= by" in line:
            return index
    return 1


def _write_validation_copy(case_path: Path) -> Path:
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    validation_path = VALIDATION_DIR / case_path.name
    validation_path.write_text(case_path.read_text(encoding="utf-8"), encoding="utf-8")
    return validation_path


async def _query_with_mcp(validation_path: Path, goal_line: int) -> dict[str, Any]:
    relative_path = lean_workspace_relative_path(validation_path)
    async with open_lean_mcp_session() as session:
        diagnostics = await session.call_tool(
            "lean_diagnostic_messages",
            {"file_path": relative_path},
        )
        goal = await session.call_tool(
            "lean_goal",
            {"file_path": relative_path, "line": goal_line},
        )

    diagnostics_structured = getattr(diagnostics, "structuredContent", None) or {}
    goal_structured = getattr(goal, "structuredContent", None) or {}
    errors, warnings = parse_diagnostics(diagnostics_structured)
    return {
        "relative_path": relative_path,
        "goal_line": goal_line,
        "diagnostics": diagnostics_structured,
        "goal": goal_structured,
        "errors": errors,
        "warnings": warnings,
    }


def _compiler_validate(validation_path: Path) -> dict[str, Any]:
    relative_path = validation_path.relative_to(LEAN_WORKSPACE)
    result = subprocess.run(
        ["lake", "env", "lean", str(relative_path)],
        cwd=LEAN_WORKSPACE,
        capture_output=True,
        text=True,
        timeout=300,
    )
    combined = (result.stdout + "\n" + result.stderr).strip()
    return {
        "command": ["lake", "env", "lean", str(relative_path)],
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "has_errors": result.returncode != 0,
        "has_sorry_warning": "declaration uses `sorry`" in combined,
    }


def _validate_case(case_path: Path) -> dict[str, Any]:
    lean_code = case_path.read_text(encoding="utf-8")
    validation_path = _write_validation_copy(case_path)
    try:
        mcp_result = asyncio.run(_query_with_mcp(validation_path, _goal_line(lean_code)))
        compiler_result = _compiler_validate(validation_path)
        return {
            "mcp": mcp_result,
            "compiler": compiler_result,
        }
    finally:
        if validation_path.exists():
            validation_path.unlink()


def _run_case(case_path: Path) -> dict[str, Any]:
    lean_code = case_path.read_text(encoding="utf-8")
    pipeline_log: list[dict[str, Any]] = []

    def on_log(entry: dict[str, Any]) -> None:
        pipeline_log.append(entry)

    started = time.time()
    try:
        result = run_pipeline(
            raw_input=lean_code,
            preformalized_theorem=lean_code,
            on_log=on_log,
            use_cache=False,
        )
        error = None
    except Exception as exc:
        result = None
        error = str(exc)

    return {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": time.time() - started,
        "pipeline_log": pipeline_log,
        "result": result,
        "error": error,
    }


def _artifact_path(case_path: Path) -> Path:
    return OUTPUT_DIR / f"{case_path.stem}.json"


def _write_case_artifact(case_path: Path, record: dict[str, Any]) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact_path = _artifact_path(case_path)
    artifact_path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return artifact_path


def _error_preview(messages: list[str], limit: int = 3) -> str:
    if not messages:
        return "(none)"
    return "\n".join(messages[:limit])


def _render_summary(records: list[dict[str, Any]]) -> str:
    lines = [
        "# Phase 1 Stress Test Results",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        "This report is factual. It records compiler validation and agentic-pipeline",
        "behavior exactly as observed for the Phase 1 stress suite.",
        "",
    ]

    for record in records:
        case_path = Path(record["source_path"])
        validation = record["validation"]
        run = record["run"]
        result = run["result"] or {}
        mcp_validation = validation["mcp"]
        compiler_validation = validation["compiler"]

        lines.extend(
            [
                f"## {case_path.name}",
                "",
                f"- Source file: `{case_path}`",
                f"- Raw artifact: `{record['artifact_path']}`",
                f"- MCP validation errors: {len(mcp_validation['errors'])}",
                f"- MCP validation warnings: {len(mcp_validation['warnings'])}",
                f"- Lean compiler return code: {compiler_validation['returncode']}",
                f"- Lean compiler reported `sorry`: {compiler_validation['has_sorry_warning']}",
            ]
        )

        if run["error"] is not None:
            lines.extend(
                [
                    f"- Pipeline execution error: {run['error']}",
                    "",
                ]
            )
            continue

        lines.extend(
            [
                f"- Pipeline success: {result.get('success')}",
                f"- Final phase: {result.get('phase')}",
                f"- Partial result: {result.get('partial')}",
                f"- Stop reason: {result.get('stop_reason')}",
                f"- Round-trip count: {result.get('attempts_used')}",
                f"- Tactic calls observed: {len(result.get('tactic_calls', []))}",
                f"- Tool trace events: {len(result.get('tool_trace', []))}",
                f"- Pipeline log entries: {len(run.get('pipeline_log', []))}",
                f"- Final error count: {len(result.get('errors', []))}",
                f"- Final warning count: {len(result.get('warnings', []))}",
                f"- Pipeline elapsed seconds: {result.get('elapsed_seconds')}",
                f"- Agent summary: {result.get('agent_summary', '')}",
                f"- Output Lean artifact: {result.get('output_lean')}",
                "",
                "### MCP Diagnostics Preview",
                "",
                "```text",
                _error_preview(mcp_validation["errors"] or mcp_validation["warnings"]),
                "```",
                "",
                "### Final Errors Preview",
                "",
                "```text",
                _error_preview(result.get("errors", [])),
                "```",
                "",
                "### Final Warnings Preview",
                "",
                "```text",
                _error_preview(result.get("warnings", [])),
                "```",
                "",
            ]
        )

    return "\n".join(lines)


def main() -> int:
    args = _parse_args()
    if not os.environ.get("MISTRAL_API_KEY"):
        print("MISTRAL_API_KEY is required to run the stress suite.", file=sys.stderr)
        return 1

    original_proof = PROOF_PATH.read_text(encoding="utf-8") if PROOF_PATH.exists() else None
    records: list[dict[str, Any]] = []
    selected_cases = _select_cases(args.cases)
    summary_path = Path(args.summary_path).resolve()

    try:
        for case_path in selected_cases:
            validation = _validate_case(case_path)
            run = _run_case(case_path)
            record = {
                "source_path": str(case_path),
                "validation": validation,
                "run": run,
            }
            artifact_path = _write_case_artifact(case_path, record)
            record["artifact_path"] = str(artifact_path)
            records.append(record)

        summary_path.write_text(_render_summary(records), encoding="utf-8")
        print(f"Wrote summary report to {summary_path}")
        return 0
    finally:
        if original_proof is None:
            if PROOF_PATH.exists():
                PROOF_PATH.unlink()
        else:
            PROOF_PATH.write_text(original_proof, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
