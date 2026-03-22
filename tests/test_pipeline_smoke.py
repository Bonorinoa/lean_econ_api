"""
Standalone smoke tests for pipeline.py.

Usage:
  pytest tests/test_pipeline_smoke.py
"""

from __future__ import annotations

from pipeline import formalize_claim, parse_claim

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
