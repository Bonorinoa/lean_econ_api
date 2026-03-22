"""Tests for scripts/run_phase1_stress_tests.py."""

from __future__ import annotations

import sys
from unittest.mock import patch

import run_phase1_stress_tests


def test_goal_line_and_error_preview() -> None:
    lean_code = "import Mathlib\n\ntheorem demo : True := by\n  trivial\n"
    assert run_phase1_stress_tests._goal_line(lean_code) == 3
    assert run_phase1_stress_tests._error_preview([]) == "(none)"


def test_main_writes_summary(tmp_path, monkeypatch) -> None:
    case_path = tmp_path / "case.lean"
    case_path.write_text(
        "import Mathlib\n\ntheorem demo : True := by\n  trivial\n", encoding="utf-8"
    )
    proof_path = tmp_path / "Proof.lean"
    proof_path.write_text("original proof file", encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    artifact_path = tmp_path / "artifact.json"

    monkeypatch.setattr(run_phase1_stress_tests, "PROOF_PATH", proof_path)

    argv = [
        "run_phase1_stress_tests.py",
        "--summary-path",
        str(summary_path),
    ]

    with patch.object(run_phase1_stress_tests, "_select_cases", return_value=[case_path]):
        with patch.object(
            run_phase1_stress_tests,
            "_validate_case",
            return_value={
                "mcp": {"errors": [], "warnings": [], "goal": {}, "diagnostics": {}},
                "compiler": {
                    "returncode": 0,
                    "has_sorry_warning": False,
                    "stdout": "",
                    "stderr": "",
                },
            },
        ):
            with patch.object(
                run_phase1_stress_tests,
                "_run_case",
                return_value={
                    "pipeline_log": [],
                    "error": None,
                    "result": {
                        "success": True,
                        "phase": "verified",
                        "partial": False,
                        "stop_reason": None,
                        "attempts_used": 1,
                        "tactic_calls": [],
                        "tool_trace": [],
                        "errors": [],
                        "warnings": [],
                        "elapsed_seconds": 1.0,
                        "agent_summary": "ok",
                        "output_lean": None,
                    },
                },
            ):
                with patch.object(
                    run_phase1_stress_tests,
                    "_write_case_artifact",
                    return_value=artifact_path,
                ):
                    with patch.object(sys, "argv", argv):
                        with patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}, clear=False):
                            exit_code = run_phase1_stress_tests.main()

    assert exit_code == 0
    assert "Phase 1 Stress Test Results" in summary_path.read_text(encoding="utf-8")
    assert proof_path.read_text(encoding="utf-8") == "original proof file"
