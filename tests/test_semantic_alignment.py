"""Regression checks for semantic-alignment grading helpers."""

from __future__ import annotations

from unittest.mock import patch

import semantic_alignment


def test_grade_semantic_alignment_success() -> None:
    response = """\
```json
{"score": 4, "verdict": "mostly_faithful", "rationale": "Close match.",
"trivialization_flags": ["minor_simplification"]}
```"""
    with patch.object(semantic_alignment, "call_leanstral", return_value=response):
        result = semantic_alignment.grade_semantic_alignment(
            "claim", "theorem one : True := by trivial"
        )
    assert result["generated"] is True
    assert result["score"] == 4
    assert result["verdict"] == "mostly_faithful"
    assert result["trivialization_flags"] == ["minor_simplification"]


def test_grade_semantic_alignment_failure_fallback() -> None:
    with patch.object(semantic_alignment, "call_leanstral", side_effect=RuntimeError("api down")):
        result = semantic_alignment.grade_semantic_alignment(
            "claim", "theorem one : True := by trivial"
        )
    assert result["generated"] is False
    assert result["score"] is None
    assert result["verdict"] == "grading_error"
    assert "api down" in result["rationale"]
