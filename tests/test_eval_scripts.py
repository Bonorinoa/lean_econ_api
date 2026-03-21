"""Smoke tests for evaluation CLI scripts."""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(SCRIPTS_DIR))

import analyze_traces


def _run_case(name: str, fn) -> bool:
    try:
        fn()
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False
    print(f"{name}: PASS")
    return True


def _test_analyze_traces_cli() -> None:
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


def main() -> int:
    print("=" * 60)
    print("LeanEcon Eval Script Tests")
    print("=" * 60)

    results = {
        "analyze_traces_cli": _run_case(
            "analyze_traces_cli",
            _test_analyze_traces_cli,
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
