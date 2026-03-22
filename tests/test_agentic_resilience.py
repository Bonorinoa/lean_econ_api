"""
Focused regression checks for Phase 2 agentic resilience helpers.

Usage:
  pytest tests/test_agentic_resilience.py
  python tests/test_agentic_resilience.py
"""

from __future__ import annotations

import pytest

from agentic_prover import (
    AgenticToolTracker,
    CIRCUIT_BREAKER_WARNING,
    TraceRecorder,
    _install_guarded_execute_function_calls,
    _is_code_3001_error,
    _is_retryable_run_error,
    _make_apply_tactic,
    _parse_diagnostic_payload,
)
from mistralai.client.models.functioncallentry import FunctionCallEntry
from mistralai.extra.run.context import RunContext
from mcp_runtime import LEAN_WORKSPACE
from proof_file_controller import ProofFileController


class _FakeAPIError(Exception):
    def __init__(self, status_code: int, message: str = "api failure"):
        super().__init__(message)
        self.status_code = status_code


def test_retryable_error_detection() -> None:
    assert _is_retryable_run_error(_FakeAPIError(429))
    assert _is_retryable_run_error(_FakeAPIError(503))
    assert not _is_retryable_run_error(_FakeAPIError(500))


def test_code_3001_detection() -> None:
    err = Exception(
        '{"object":"Error","detail":[{"msg":"Value error, Either inputs or tool_confirmations must be provided.","code":3001}]}'
    )
    assert _is_code_3001_error(err)


@pytest.mark.live
def test_apply_tactic_returns_nonempty_message() -> None:
    tmp_path = LEAN_WORKSPACE / "LeanEcon" / "_AgenticResilienceTmp.lean"
    controller = ProofFileController(working_file=tmp_path)
    try:
        controller.initialize(
            """\
import Mathlib

theorem trivial_truth : True := by
  sorry
"""
        )
        apply_tactic, tactic_log = _make_apply_tactic(controller, TraceRecorder())
        result = apply_tactic("trivial")
        assert result.strip()
        assert "lean_diagnostic_messages" in result
        assert tactic_log and tactic_log[0]["tactic"] == "trivial"
    finally:
        controller.cleanup()


def test_parse_diagnostic_payload() -> None:
    payload = _parse_diagnostic_payload(
        '[{"type":"text","text":"{\\"success\\": false, \\"items\\": ['
        '{\\"severity\\": \\"error\\", \\"message\\": \\"bad tactic\\", \\"line\\": 7, \\"column\\": 3},'
        '{\\"severity\\": \\"warning\\", \\"message\\": \\"declaration uses `sorry`\\"}'
        ']}"}]'
    )
    assert payload is not None
    assert payload["errors"] == ["line 7: bad tactic"]
    assert payload["warnings"] == ["declaration uses `sorry`"]


def test_default_controller_paths_are_unique() -> None:
    first = ProofFileController()
    second = ProofFileController()
    assert first.working_file != second.working_file
    assert first.working_file.name.startswith("AgenticProof_")
    assert second.working_file.name.startswith("AgenticProof_")


@pytest.mark.asyncio
async def test_circuit_breaker() -> None:
    run_ctx = RunContext(model="dummy")

    def apply_tactic(tactic: str) -> str:
        """Write a tactic candidate."""
        return f"applied {tactic}"

    def lean_diagnostic_messages(file_path: str) -> str:
        """Check diagnostics for the working Lean file."""
        return f"checked {file_path}"

    run_ctx.register_func(apply_tactic)
    run_ctx.register_func(lean_diagnostic_messages)

    tracker = AgenticToolTracker()
    trace_recorder = TraceRecorder()
    tactic_call_log: list[dict] = []
    _install_guarded_execute_function_calls(run_ctx, tracker, trace_recorder, tactic_call_log)

    apply_calls = [
        FunctionCallEntry(
            tool_call_id=f"apply-{index}",
            name="apply_tactic",
            arguments={"tactic": f"exact proof_{index}"},
        )
        for index in range(6)
    ]
    apply_results = await run_ctx.execute_function_calls(apply_calls)
    assert len(apply_results) == 6
    assert apply_results[-1].result == CIRCUIT_BREAKER_WARNING
    assert tracker.circuit_breaker_hits == 1
    assert tracker.total_apply_calls == 5

    diag_result = await run_ctx.execute_function_calls(
        [
            FunctionCallEntry(
                tool_call_id="diag-1",
                name="lean_diagnostic_messages",
                arguments={"file_path": "LeanEcon/AgenticProof_test.lean"},
            )
        ]
    )
    assert diag_result[0].result.strip()
    assert tracker.total_diagnostic_calls == 1
    assert tracker.consecutive_apply_without_diagnostics == 0

    post_diag_apply = await run_ctx.execute_function_calls(
        [
            FunctionCallEntry(
                tool_call_id="apply-after-diag",
                name="apply_tactic",
                arguments={"tactic": "exact reset_ok"},
            )
        ]
    )
    assert post_diag_apply[0].result != CIRCUIT_BREAKER_WARNING
    assert "applied exact reset_ok" in post_diag_apply[0].result


@pytest.mark.asyncio
async def test_trace_capture() -> None:
    run_ctx = RunContext(model="dummy")
    trace_recorder = TraceRecorder()
    tactic_call_log: list[dict] = []

    def apply_tactic(tactic: str) -> str:
        return f"applied {tactic}"

    def lean_diagnostic_messages(file_path: str) -> str:
        return (
            '[{"type":"text","text":"{'
            '\\"success\\": false,'
            '\\"items\\": ['
            '{\\"severity\\": \\"error\\", \\"message\\": \\"unknown identifier x\\", \\"line\\": 9, \\"column\\": 2}'
            "]}"
            '"}]'
        )

    run_ctx.register_func(apply_tactic)
    run_ctx.register_func(lean_diagnostic_messages)
    _install_guarded_execute_function_calls(run_ctx, AgenticToolTracker(), trace_recorder, tactic_call_log)

    trace_recorder.latest_kernel_errors = ["line 4: previous failure"]
    trace_recorder.latest_kernel_warnings = ["line 4: warning"]
    trace_recorder.note_tactic_attempt(tactic_call_log, "exact h")

    await run_ctx.execute_function_calls(
        [
            FunctionCallEntry(
                tool_call_id="diag-link",
                name="lean_diagnostic_messages",
                arguments={"file_path": "LeanEcon/AgenticProof_trace.lean"},
            )
        ]
    )

    assert tactic_call_log[0]["triggering_errors"] == ["line 4: previous failure"]
    assert tactic_call_log[0]["post_diagnostic_errors"] == ["line 9: unknown identifier x"]
    assert tactic_call_log[0]["successful"] is False
    tool_entries = [entry for entry in trace_recorder.entries if entry.get("type") == "tool_call"]
    assert tool_entries
    assert tool_entries[0]["tool_name"] == "lean_diagnostic_messages"
    assert tool_entries[0]["kernel_errors"] == ["line 9: unknown identifier x"]


# ---------------------------------------------------------------------------
# Standalone runner (fallback)
# ---------------------------------------------------------------------------

def _run_case(name: str, fn) -> bool:
    try:
        fn()
        ok = True
    except Exception as exc:
        ok = False
        print(f"{name}: FAIL")
        print(f"  error: {exc}")
    else:
        print(f"{name}: PASS")
    return ok


def main() -> int:
    import asyncio

    print("=" * 60)
    print("LeanEcon Agentic Resilience Tests")
    print("=" * 60)

    results = {
        "retryable_error_detection": _run_case(
            "retryable_error_detection",
            test_retryable_error_detection,
        ),
        "code_3001_detection": _run_case(
            "code_3001_detection",
            test_code_3001_detection,
        ),
        "apply_tactic_returns_nonempty_message": _run_case(
            "apply_tactic_returns_nonempty_message",
            test_apply_tactic_returns_nonempty_message,
        ),
        "parse_diagnostic_payload": _run_case(
            "parse_diagnostic_payload",
            test_parse_diagnostic_payload,
        ),
        "default_controller_paths_are_unique": _run_case(
            "default_controller_paths_are_unique",
            test_default_controller_paths_are_unique,
        ),
        "circuit_breaker": _run_case(
            "circuit_breaker",
            lambda: asyncio.run(test_circuit_breaker()),
        ),
        "trace_capture": _run_case(
            "trace_capture",
            lambda: asyncio.run(test_trace_capture()),
        ),
    }

    print("\n" + "=" * 60)
    print("Results:")
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
