"""Regression checks for semantic-alignment grading helpers."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import provider_telemetry
import semantic_alignment


@pytest.fixture(autouse=True)
def _stub_semantic_alignment_client():
    with patch.object(semantic_alignment, "get_client", return_value=object()):
        yield


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


def test_grade_semantic_alignment_collects_provider_telemetry() -> None:
    response = """\
```json
{"score": 5, "verdict": "faithful", "rationale": "Close match.",
"trivialization_flags": []}
```"""

    def fake_call(*args, telemetry_out=None, **kwargs):
        assert telemetry_out is not None
        telemetry_out.append(
            provider_telemetry.build_provider_call_telemetry(
                endpoint="semantic_grade",
                model="leanstral",
                usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
                latency_ms=4.4,
                retry_count=0,
            )
        )
        return response

    with patch.object(semantic_alignment, "call_leanstral", side_effect=fake_call):
        result = semantic_alignment.grade_semantic_alignment(
            "claim", "theorem one : True := by trivial", telemetry_out=[]
        )

    assert result["generated"] is True
    assert result["provider_telemetry"]["provider_call_count"] == 1
    assert result["provider_telemetry"]["local_only"] is False
