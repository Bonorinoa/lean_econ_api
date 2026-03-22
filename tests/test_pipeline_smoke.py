"""
Standalone smoke tests for pipeline.py.

Usage:
  pytest tests/test_pipeline_smoke.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pipeline as _pipeline_mod
from pipeline import formalize_claim, parse_claim, run_pipeline
from result_cache import ResultCache

RAW_LEAN_THEOREM = """\
import Mathlib
open Real

theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""


def test_parse_claim() -> None:
    raw_input = r"""
% A comment that should be removed
\begin{theorem}

Under CRRA utility, relative risk aversion is constant.

\end{theorem}
"""
    parsed = parse_claim(raw_input)
    expected = "Under CRRA utility, relative risk aversion is constant."
    assert parsed["text"] == expected, parsed["text"]


def test_raw_lean_bypass() -> None:
    result = formalize_claim(RAW_LEAN_THEOREM)
    assert result["success"] is True
    assert result["attempts"] == 0
    assert result["formalization_failed"] is False
    assert result["theorem_code"] == RAW_LEAN_THEOREM.strip()


def test_cache_hit_calls_log_run_with_from_cache_true() -> None:
    """Cache hits must be logged to eval_logger so /metrics counts them."""
    claim = "Consumers maximize utility subject to a budget constraint."
    theorem_statement = """\
theorem utility_budget_feasible : True := by
  trivial
"""
    cached_result = {
        "success": True,
        "lean_code": theorem_statement.strip(),
        "errors": [],
        "warnings": [],
        "phase": "verified",
        "proof_strategy": "Local deterministic tactic fast path",
        "proof_tactics": "trivial",
        "theorem_statement": theorem_statement.strip(),
        "formalization_attempts": 2,
        "tool_trace": [],
        "tactic_calls": [],
        "trace_schema_version": 1,
        "agent_summary": "",
        "agent_elapsed_seconds": 0.0,
        "axiom_info": None,
        "partial": False,
        "stop_reason": None,
        "from_cache": False,  # will be overwritten to True by run_pipeline
        "elapsed_seconds": 1.0,
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        cache = ResultCache(cache_file=Path(tmpdir) / "cache.json")
        cache.put(claim, cached_result)

        with (
            patch.object(_pipeline_mod, "result_cache", cache),
            patch.object(_pipeline_mod, "log_run") as mock_log_run,
        ):
            result = run_pipeline(claim, use_cache=True)

    assert result["from_cache"] is True
    assert result["elapsed_seconds"] == 0.0

    mock_log_run.assert_called_once()
    logged = mock_log_run.call_args[0][0]
    assert logged["from_cache"] is True
    assert logged["cache_replay"] is True
    assert logged["elapsed_seconds"] == 0.0
    assert logged["verification"]["success"] is True
    assert logged["stop_reason"] == "cache_hit"
    assert logged["formalization"]["theorem_code"] == theorem_statement.strip()
    assert logged["formalization"]["attempts"] == 2
    assert logged["formalization"]["model"] == "cache_replay"
    assert logged["proving"]["proof_tactics"] == "trivial"
