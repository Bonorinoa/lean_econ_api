"""
eval_logger.py

Append-only structured logging for every pipeline run.
Writes one JSON object per line to logs/runs.jsonl.

This is your evaluation dataset — never raises, never breaks the pipeline.

Usage:
  from eval_logger import log_run
  log_run(run_data_dict)
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
LOGS_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOGS_DIR / "runs.jsonl"
LOG_SCHEMA_VERSION = 2


def log_run(run_data: dict) -> None:
    """
    Append a run record to logs/runs.jsonl.

    Never raises — all errors are silently swallowed so logging never
    interrupts the pipeline.

    Args:
        run_data: Dict with pipeline run details. Will be merged with a
                  timestamp and unique run_id.
    """
    try:
        LOGS_DIR.mkdir(exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": str(uuid.uuid4()),
            "log_schema_version": LOG_SCHEMA_VERSION,
            **run_data,
        }
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass  # Logging must never break the pipeline
