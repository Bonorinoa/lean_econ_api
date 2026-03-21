"""Analyze deep agentic traces from logs/runs.jsonl."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from eval_metrics import aggregate_trace_metrics, load_jsonl_records, render_trace_metrics


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze LeanEcon deep traces from runs.jsonl.")
    parser.add_argument(
        "--runs-file",
        default=str(PROJECT_ROOT / "logs" / "runs.jsonl"),
        help="Path to the evaluation JSONL log.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "both"),
        default="both",
        help="Output format.",
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Optional path to write the machine-readable JSON summary.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    runs_path = Path(args.runs_file).resolve()
    records, malformed_lines = load_jsonl_records(runs_path)
    metrics = aggregate_trace_metrics(records)
    metrics["runs_file"] = str(runs_path)
    metrics["malformed_lines_skipped"] = malformed_lines

    if args.format in {"text", "both"}:
        print(render_trace_metrics(metrics))
        if args.format == "both":
            print()

    if args.format in {"json", "both"}:
        print(json.dumps(metrics, indent=2, ensure_ascii=False))

    if args.json_output:
        output_path = Path(args.json_output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(metrics, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
