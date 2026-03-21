"""Pre-seed the result cache from curated examples."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from result_cache import result_cache

EXAMPLES_DIR = PROJECT_ROOT / "examples"


def main() -> None:
    for lean_file in sorted(EXAMPLES_DIR.glob("*_pass.lean")):
        code = lean_file.read_text(encoding="utf-8")
        report_file = lean_file.with_name(f"{lean_file.stem}_report.md")
        report = report_file.read_text(encoding="utf-8") if report_file.exists() else ""

        result = {
            "success": True,
            "lean_code": code,
            "errors": [],
            "warnings": [],
            "proof_strategy": report.strip(),
            "proof_tactics": "(pre-verified)",
            "theorem_statement": code,
            "formalization_attempts": 0,
            "formalization_failed": False,
            "failure_reason": None,
            "output_lean": None,
            "proof_generated": True,
            "phase": "verified",
            "elapsed_seconds": 0.0,
            "from_cache": False,
            "partial": False,
            "stop_reason": None,
        }
        result_cache.put(code, result)
        print(f"Cached: {lean_file.name}")

    print(f"Cache size: {result_cache.size}")


if __name__ == "__main__":
    main()
