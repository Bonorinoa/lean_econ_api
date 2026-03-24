"""
Focused regression checks for Phase 2 agentic resilience helpers.

Usage:
  pytest tests/test_agentic_resilience.py
"""

from __future__ import annotations

import time

import pytest
from mistralai.client.models.functioncallentry import FunctionCallEntry
from mistralai.extra.run.context import RunContext

import agentic_prover
from agentic_prover import (
    CIRCUIT_BREAKER_WARNING,
    DUPLICATE_READ_ONLY_WARNING,
    LOCAL_FAST_PATH_MAX_ATTEMPTS,
    SEARCH_BUDGET_WARNING,
    SEARCH_PRECONDITION_WARNING,
    AgenticToolTracker,
    ToolBudgetExceededError,
    TraceRecorder,
    _install_guarded_execute_function_calls,
    _is_cancel_scope_error,
    _is_code_3001_error,
    _is_retryable_run_error,
    _local_fast_path_tactics,
    _make_apply_tactic,
    _normalized_interruption_warning,
    _parse_diagnostic_payload,
    _prune_agentic_tools,
    _try_local_tactic_fast_path,
)
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
        '{"object":"Error","detail":[{"msg":"Value error, Either inputs or '
        'tool_confirmations must be provided.","code":3001}]}'
    )
    assert _is_code_3001_error(err)


def test_cancel_scope_error_detection() -> None:
    """_is_cancel_scope_error detects the anyio Python 3.12+ task-mismatch error."""
    # Direct exception containing the cancel-scope message
    direct = RuntimeError(
        "Attempted to exit cancel scope in a different task than it was entered in"
    )
    assert _is_cancel_scope_error(direct)

    # Wrapped in an ExceptionGroup (as anyio task groups raise)
    wrapped = ExceptionGroup("unhandled errors in a TaskGroup", [direct])
    assert _is_cancel_scope_error(wrapped)

    # Unrelated exception should not match
    unrelated = RuntimeError("Something completely different")
    assert not _is_cancel_scope_error(unrelated)

    # Nested ExceptionGroup should also be detected
    nested = ExceptionGroup("outer", [ExceptionGroup("inner", [direct])])
    assert _is_cancel_scope_error(nested)


def test_cancel_scope_warning_is_normalized() -> None:
    warning = _normalized_interruption_warning("cancel_scope")
    assert "cancel scope" not in warning.lower()
    assert "latest proof state" in warning.lower()


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
        '{\\"severity\\": \\"error\\", \\"message\\": \\"bad tactic\\", '
        '\\"line\\": 7, \\"column\\": 3},'
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


def test_controller_normalizes_inline_sorry_stub(tmp_path) -> None:
    controller = ProofFileController(working_file=tmp_path / "InlineSorry.lean")

    try:
        lean_code = controller.initialize("theorem inline_demo : True := by sorry")
        assert "theorem inline_demo : True := by\n" in lean_code
        expected_region = (
            "  -- LEANECON_AGENTIC_TACTICS_BEGIN\n"
            "  sorry\n"
            "  -- LEANECON_AGENTIC_TACTICS_END\n"
        )
        assert expected_region in lean_code
        assert controller.current_tactic_block == "sorry"
    finally:
        controller.cleanup()


def test_prune_agentic_tools_removes_low_roi_tools() -> None:
    run_ctx = type("DummyRunCtx", (), {})()
    run_ctx._callable_tools = {
        "apply_tactic": object(),
        "lean_goal": object(),
        "lean_diagnostic_messages": object(),
        "lean_state_search": object(),
        "lean_loogle": object(),
        "lean_build": object(),
    }

    removed = _prune_agentic_tools(run_ctx)

    assert sorted(run_ctx._callable_tools) == [
        "apply_tactic",
        "lean_diagnostic_messages",
        "lean_goal",
        "lean_state_search",
    ]
    assert removed == ["lean_build", "lean_loogle"]


def test_local_fast_path_solves_trivial_theorem(monkeypatch, tmp_path) -> None:
    theorem = """\
import Mathlib

theorem trivial_truth : True := by
  sorry
"""
    controller = ProofFileController(working_file=tmp_path / "LocalFastPath.lean")
    controller.initialize(theorem)
    check_axioms_calls: list[bool] = []
    log_entries: list[dict[str, object]] = []

    def fake_verify(lean_code: str, filename=None, check_axioms: bool = True) -> dict:
        del filename
        check_axioms_calls.append(check_axioms)
        if "aesop" in lean_code:
            return {
                "success": True,
                "errors": [],
                "warnings": [],
                "output_lean": lean_code,
                "axiom_info": None,
            }
        return {
            "success": False,
            "errors": ["tactic failed"],
            "warnings": [],
            "output_lean": None,
            "axiom_info": None,
        }

    monkeypatch.setattr(agentic_prover, "verify", fake_verify)

    result = _try_local_tactic_fast_path(
        theorem,
        controller,
        on_log=log_entries.append,
        start_time=time.time(),
    )

    assert result is not None
    assert result["success"] is True
    assert result["steps_used"] == 0
    assert result["mcp_enabled"] is False
    assert result["proof_tactics"] == "aesop"
    assert result["tactic_calls"][0]["successful"] is True
    assert check_axioms_calls == [False]
    done_entry = next(
        entry
        for entry in log_entries
        if entry["stage"] == "agentic_fast_path" and entry["status"] == "done"
    )
    assert isinstance(done_entry["elapsed_ms"], float)
    assert done_entry["elapsed_ms"] >= 0.0


def test_local_fast_path_prioritizes_norm_num_for_numeric_arithmetic() -> None:
    theorem = """\
import Mathlib

theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""

    tactics = _local_fast_path_tactics(theorem)

    assert tactics[0] == "norm_num"
    assert "omega" in tactics
    assert tactics.index("norm_num") < tactics.index("aesop")


def test_local_fast_path_prioritizes_exact_hypothesis_tactics() -> None:
    theorem = """\
import Mathlib
open Real

theorem benchmark_budget_constraint
    (m p1 p2 x1 x2 : ℝ)
    (hm : m > 0) (hp1 : p1 > 0) (hp2 : p2 > 0)
    (hspend : p1 * x1 + p2 * x2 = m) :
    p1 * x1 + p2 * x2 = m := by
  sorry
"""

    tactics = _local_fast_path_tactics(theorem)

    assert tactics[:3] == ["exact hspend", "simpa using hspend", "assumption"]
    assert tactics.index("exact hspend") < tactics.index("omega")


def test_local_fast_path_respects_compile_budget(monkeypatch, tmp_path) -> None:
    theorem = """\
import Mathlib

theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""
    controller = ProofFileController(working_file=tmp_path / "LocalFastPathBudget.lean")
    controller.initialize(theorem)

    attempted_tactics: list[str] = []

    def fake_verify(lean_code: str, filename=None, check_axioms: bool = True) -> dict:
        del filename, check_axioms
        if "norm_num" in lean_code:
            attempted_tactics.append("norm_num")
        elif "omega" in lean_code:
            attempted_tactics.append("omega")
        elif "ring_nf" in lean_code:
            attempted_tactics.append("ring_nf")
        elif "ring" in lean_code:
            attempted_tactics.append("ring")
        else:
            attempted_tactics.append("other")
        return {
            "success": False,
            "errors": ["no tactic worked"],
            "warnings": [],
            "output_lean": None,
            "axiom_info": None,
        }

    monkeypatch.setattr(agentic_prover, "verify", fake_verify)

    result = _try_local_tactic_fast_path(
        theorem,
        controller,
        on_log=None,
        start_time=time.time(),
    )

    assert result is None
    assert len(attempted_tactics) == LOCAL_FAST_PATH_MAX_ATTEMPTS
    assert attempted_tactics == ["norm_num", "omega", "ring_nf", "ring"]
    assert controller.current_tactic_block == "sorry"


def test_local_fast_path_restores_initial_state_on_failure(monkeypatch, tmp_path) -> None:
    theorem = """\
import Mathlib

theorem trivial_truth : True := by
  sorry
"""
    controller = ProofFileController(working_file=tmp_path / "LocalFastPathFail.lean")
    controller.initialize(theorem)

    monkeypatch.setattr(
        agentic_prover,
        "verify",
        lambda *args, **kwargs: {
            "success": False,
            "errors": ["no tactic worked"],
            "warnings": [],
            "output_lean": None,
            "axiom_info": None,
        },
    )

    result = _try_local_tactic_fast_path(
        theorem,
        controller,
        on_log=None,
        start_time=time.time(),
    )

    assert result is None
    assert controller.current_tactic_block == "sorry"


def test_interrupted_run_logs_terminal_verify_stage_for_partial_success(monkeypatch) -> None:
    class StubController:
        current_tactic_block = "exact trivial"
        current_lean_code = "import Mathlib\n\ntheorem interrupted_demo : True := by\n  trivial\n"

    log_entries: list[dict[str, object]] = []

    monkeypatch.setattr(
        agentic_prover,
        "verify",
        lambda lean_code: {
            "success": True,
            "errors": [],
            "warnings": [],
            "output_lean": lean_code,
            "axiom_info": None,
        },
    )

    result = agentic_prover._build_interrupted_run_result(
        controller=StubController(),
        model_text="partial proof",
        tool_trace_entries=[],
        tactic_call_log=[],
        steps_used=2,
        start_time=time.time() - 0.1,
        agentic_run_started_at=time.time() - 0.05,
        interruption_message="Leanstral timed out before finishing the loop.",
        stop_reason=agentic_prover.STOP_TIMEOUT,
        agent_summary="Interrupted run",
        partial=True,
        on_log=log_entries.append,
    )

    assert result["success"] is True
    assert result["partial"] is True
    assert result["stop_reason"] == agentic_prover.STOP_PROOF_COMPLETE
    assert [
        (entry["stage"], entry["status"])
        for entry in log_entries
        if entry["stage"] in {"agentic_run", "agentic_verify"}
    ] == [
        ("agentic_run", "error"),
        ("agentic_verify", "running"),
        ("agentic_verify", "done"),
    ]
    terminal_entries = [
        entry
        for entry in log_entries
        if entry["stage"] in {"agentic_run", "agentic_verify"} and entry["status"] != "running"
    ]
    assert all(isinstance(entry["elapsed_ms"], float) for entry in terminal_entries)


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
async def test_search_budget_blocks_low_roi_search() -> None:
    run_ctx = RunContext(model="dummy")

    def lean_state_search(file_path: str, line: int, column: int) -> str:
        return f"search {file_path}:{line}:{column}"

    run_ctx.register_func(lean_state_search)

    tracker = AgenticToolTracker(max_search_tool_calls=0)
    trace_recorder = TraceRecorder()
    tactic_call_log: list[dict] = [{"successful": False}]
    _install_guarded_execute_function_calls(run_ctx, tracker, trace_recorder, tactic_call_log)

    result = await run_ctx.execute_function_calls(
        [
            FunctionCallEntry(
                tool_call_id="search-1",
                name="lean_state_search",
                arguments={"file_path": "LeanEcon/Test.lean", "line": 4, "column": 1},
            )
        ]
    )

    assert result[0].result == SEARCH_BUDGET_WARNING
    assert tracker.blocked_tool_calls == 1
    assert tracker.total_tool_calls == 1
    assert tracker.total_search_calls == 0


@pytest.mark.asyncio
async def test_search_requires_failed_tactic_attempt() -> None:
    run_ctx = RunContext(model="dummy")

    def lean_state_search(file_path: str, line: int, column: int) -> str:
        return f"search {file_path}:{line}:{column}"

    run_ctx.register_func(lean_state_search)

    tracker = AgenticToolTracker()
    trace_recorder = TraceRecorder()
    tactic_call_log: list[dict] = []
    _install_guarded_execute_function_calls(run_ctx, tracker, trace_recorder, tactic_call_log)

    result = await run_ctx.execute_function_calls(
        [
            FunctionCallEntry(
                tool_call_id="search-precondition",
                name="lean_state_search",
                arguments={"file_path": "LeanEcon/Test.lean", "line": 4, "column": 1},
            )
        ]
    )

    assert result[0].result == SEARCH_PRECONDITION_WARNING
    assert tracker.blocked_tool_calls == 1
    assert tracker.search_budget_hits == 0
    assert tracker.total_search_calls == 0


@pytest.mark.asyncio
async def test_duplicate_read_only_call_is_blocked() -> None:
    run_ctx = RunContext(model="dummy")

    def lean_goal(file_path: str, line: int) -> str:
        return f"goal {file_path}:{line}"

    run_ctx.register_func(lean_goal)

    tracker = AgenticToolTracker(max_consecutive_read_only_calls=10)
    trace_recorder = TraceRecorder()
    tactic_call_log: list[dict] = []
    _install_guarded_execute_function_calls(run_ctx, tracker, trace_recorder, tactic_call_log)

    await run_ctx.execute_function_calls(
        [
            FunctionCallEntry(
                tool_call_id="goal-1",
                name="lean_goal",
                arguments={"file_path": "LeanEcon/Test.lean", "line": 4},
            )
        ]
    )
    second = await run_ctx.execute_function_calls(
        [
            FunctionCallEntry(
                tool_call_id="goal-2",
                name="lean_goal",
                arguments={"file_path": "LeanEcon/Test.lean", "line": 4},
            )
        ]
    )

    assert second[0].result == DUPLICATE_READ_ONLY_WARNING
    assert tracker.blocked_tool_calls == 1
    assert tracker.duplicate_read_only_hits == 1


@pytest.mark.asyncio
async def test_read_only_loop_budget_stops_run() -> None:
    run_ctx = RunContext(model="dummy")

    def lean_goal(file_path: str, line: int) -> str:
        return f"goal {file_path}:{line}"

    run_ctx.register_func(lean_goal)

    tracker = AgenticToolTracker(max_consecutive_read_only_calls=1)
    trace_recorder = TraceRecorder()
    tactic_call_log: list[dict] = []
    _install_guarded_execute_function_calls(run_ctx, tracker, trace_recorder, tactic_call_log)

    await run_ctx.execute_function_calls(
        [
            FunctionCallEntry(
                tool_call_id="goal-1",
                name="lean_goal",
                arguments={"file_path": "LeanEcon/Test.lean", "line": 4},
            )
        ]
    )

    with pytest.raises(ToolBudgetExceededError):
        await run_ctx.execute_function_calls(
            [
                FunctionCallEntry(
                    tool_call_id="goal-2",
                    name="lean_goal",
                    arguments={"file_path": "LeanEcon/Test.lean", "line": 4},
                )
            ]
        )


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
            '{\\"severity\\": \\"error\\", \\"message\\": \\"unknown '
            'identifier x\\", \\"line\\": 9, \\"column\\": 2}'
            "]}"
            '"}]'
        )

    run_ctx.register_func(apply_tactic)
    run_ctx.register_func(lean_diagnostic_messages)
    _install_guarded_execute_function_calls(
        run_ctx, AgenticToolTracker(), trace_recorder, tactic_call_log
    )

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
