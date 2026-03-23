"""CLI wrapper for the LeanEcon benchmark harness."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _main() -> int:
    from benchmark_harness import main

    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
