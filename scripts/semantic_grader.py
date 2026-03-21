"""CLI for semantic-alignment grading of Lean formalizations."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

from semantic_alignment import grade_semantic_alignment


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grade semantic alignment for LeanEcon formalizations.")
    parser.add_argument("--claim", default=None, help="Original raw claim text.")
    parser.add_argument("--claim-file", default=None, help="Path to a file containing the original claim.")
    parser.add_argument(
        "--theorem-file",
        default=None,
        help="Path to a file containing the generated Lean theorem code.",
    )
    parser.add_argument(
        "--jsonl",
        default=None,
        help=(
            "Optional JSONL input containing `original_raw_claim`/`raw_claim` and "
            "`generated_theorem_code`/`theorem_code` pairs."
        ),
    )
    parser.add_argument(
        "--json-output",
        default=None,
        help="Optional path to write JSON results.",
    )
    return parser.parse_args()


def _read_text_arg(inline_value: str | None, file_value: str | None, label: str) -> str:
    if inline_value:
        return inline_value
    if file_value:
        return Path(file_value).read_text(encoding="utf-8")
    raise SystemExit(f"{label} is required.")


def _grade_jsonl(path: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            continue
        claim = payload.get("original_raw_claim") or payload.get("raw_claim")
        theorem_code = payload.get("generated_theorem_code") or payload.get("theorem_code")
        if not claim or not theorem_code:
            continue
        result = grade_semantic_alignment(str(claim), str(theorem_code))
        results.append(
            {
                "line_number": line_number,
                "claim_id": payload.get("id"),
                "semantic_grade": result,
            }
        )
    return results


def main() -> int:
    args = _parse_args()
    json_output_path = Path(args.json_output).resolve() if args.json_output else None

    if args.jsonl:
        results: dict[str, Any] = {
            "grades": _grade_jsonl(Path(args.jsonl).resolve()),
        }
        print(json.dumps(results, indent=2, ensure_ascii=False))
        if json_output_path is not None:
            json_output_path.parent.mkdir(parents=True, exist_ok=True)
            json_output_path.write_text(
                json.dumps(results, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return 0

    claim_text = _read_text_arg(args.claim, args.claim_file, "--claim/--claim-file")
    theorem_file = args.theorem_file
    if not theorem_file:
        raise SystemExit("--theorem-file is required when grading a single pair.")
    theorem_code = Path(theorem_file).read_text(encoding="utf-8")

    result = grade_semantic_alignment(claim_text, theorem_code)
    print(json.dumps(result, indent=2, ensure_ascii=False))

    if json_output_path is not None:
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        json_output_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
