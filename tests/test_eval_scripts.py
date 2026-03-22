"""Smoke tests for evaluation CLI scripts."""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import analyze_traces


def test_analyze_traces_cli() -> None:
    entries = [
        json.dumps(
            {
                "verification": {"success": True},
                "proving": {
                    "proof_tactics": "constructor\n· exact h",
                    "tool_trace": [{"type": "tool_call"}, {"type": "tool_call"}],
                    "tactic_calls": [{"tactic": "constructor\n· exact h", "successful": True}],
                },
            }
        ),
        "{bad json",
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        runs_path = Path(tmpdir) / "runs.jsonl"
        runs_path.write_text("\n".join(entries) + "\n", encoding="utf-8")
        stdout = io.StringIO()
        argv = [
            "analyze_traces.py",
            "--runs-file",
            str(runs_path),
            "--format",
            "json",
        ]
        with patch.object(sys, "argv", argv), redirect_stdout(stdout):
            exit_code = analyze_traces.main()

    payload = json.loads(stdout.getvalue())
    assert exit_code == 0
    assert payload["runs_considered"] == 1
    assert payload["malformed_lines_skipped"] == 1
