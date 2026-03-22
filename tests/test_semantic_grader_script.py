"""Tests for scripts/semantic_grader.py."""

from __future__ import annotations

import json
import sys
from unittest.mock import patch

import semantic_grader


def test_semantic_grader_single_pair(tmp_path, capsys) -> None:
    theorem_file = tmp_path / "theorem.lean"
    theorem_file.write_text("theorem one_plus_one : 1 + 1 = 2 := by norm_num\n", encoding="utf-8")

    argv = [
        "semantic_grader.py",
        "--claim",
        "1 + 1 = 2",
        "--theorem-file",
        str(theorem_file),
    ]
    expected = {
        "score": 5,
        "verdict": "faithful",
        "rationale": "Exact match.",
        "trivialization_flags": [],
        "generated": True,
    }

    with patch.object(semantic_grader, "grade_semantic_alignment", return_value=expected):
        with patch.object(sys, "argv", argv):
            exit_code = semantic_grader.main()

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_semantic_grader_jsonl_mode_writes_output(tmp_path, capsys) -> None:
    jsonl_path = tmp_path / "pairs.jsonl"
    jsonl_path.write_text(
        json.dumps(
            {
                "id": "case_1",
                "raw_claim": "claim",
                "theorem_code": "theorem demo : True := by trivial",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_path = tmp_path / "semantic.json"
    argv = [
        "semantic_grader.py",
        "--jsonl",
        str(jsonl_path),
        "--json-output",
        str(output_path),
    ]

    with patch.object(
        semantic_grader,
        "grade_semantic_alignment",
        return_value={
            "score": 4,
            "verdict": "mostly_faithful",
            "rationale": "Close enough.",
            "trivialization_flags": [],
            "generated": True,
        },
    ):
        with patch.object(sys, "argv", argv):
            exit_code = semantic_grader.main()

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["grades"][0]["claim_id"] == "case_1"
    assert output_path.is_file()
