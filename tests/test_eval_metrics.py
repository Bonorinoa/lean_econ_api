"""Regression checks for trace-analysis helpers."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from eval_metrics import aggregate_trace_metrics, extract_tactic_heads, load_jsonl_records


def test_load_jsonl_records_tolerates_malformed_lines() -> None:
    entries = [
        json.dumps({"verification": {"success": True}}),
        "{bad json",
        json.dumps({"verification": {"success": False}}),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "runs.jsonl"
        path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        records, malformed = load_jsonl_records(path)
    assert len(records) == 2
    assert malformed == 1


def test_extract_tactic_heads() -> None:
    tactic_block = """\
constructor
· exact h1
· simp
"""
    assert extract_tactic_heads(tactic_block) == ["constructor", "exact", "simp"]


def test_aggregate_trace_metrics() -> None:
    records = [
        {
            "success": True,
            "proof_tactics": "constructor\n· exact h\n· simp",
            "tool_trace": [
                {"type": "tool_call", "tool_name": "apply_tactic"},
                {"type": "tool_call", "tool_name": "lean_diagnostic_messages"},
                {"type": "tool_call", "tool_name": "lean_state_search"},
            ],
            "tactic_calls": [
                {"tactic": "constructor\n· exact h\n· simp", "successful": True},
            ],
        },
        {
            "success": False,
            "tool_trace": [
                {
                    "type": "tool_call",
                    "tool_name": "lean_diagnostic_messages",
                    "kernel_errors": ["line 7: unknown identifier x"],
                    "blocked": True,
                }
            ],
            "tactic_calls": [
                {"tactic": "exact x", "successful": False},
            ],
            "errors": ["line 7: unknown identifier x"],
        },
    ]
    metrics = aggregate_trace_metrics(records)
    assert metrics["runs_considered"] == 2
    assert metrics["total_tool_calls"] == 4
    assert metrics["successful_tactic_applications"] == 1
    assert metrics["tool_call_efficiency"] == 0.25
    assert metrics["tool_call_waste_ratio"] == 0.75
    assert metrics["write_tool_calls"] == 1
    assert metrics["diagnostic_tool_calls"] == 2
    assert metrics["search_tool_calls"] == 1
    assert metrics["blocked_tool_calls"] == 1
    assert metrics["tactic_depth_average"] == 3.0
    assert metrics["error_frequency"]["line 7: unknown identifier x"] == 1
