"""
eval_logger.py

Append-only structured logging for every pipeline run.
Writes one JSON object per line to `logs/runs.jsonl` by default, or to
`${LEANECON_STATE_DIR}/logs/runs.jsonl` when `LEANECON_STATE_DIR` is set.

This is your evaluation dataset — never raises, never breaks the pipeline.

Usage:
  from eval_logger import log_run
  log_run(run_data_dict)
"""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
LOG_SCHEMA_VERSION = 2


def _state_dir() -> Path:
    configured = os.environ.get("LEANECON_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return PROJECT_ROOT


LOGS_DIR = _state_dir() / "logs"
LOG_FILE = LOGS_DIR / "runs.jsonl"


def log_run(run_data: dict) -> None:
    """
    Append a run record to the configured JSONL run log.

    Never raises — all errors are silently swallowed so logging never
    interrupts the pipeline.

    Args:
        run_data: Dict with pipeline run details. Will be merged with a
                  timestamp and unique run_id.
    """
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
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
