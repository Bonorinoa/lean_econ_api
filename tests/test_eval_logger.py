"""Tests for env-configurable logging paths."""

from __future__ import annotations

import importlib


def test_eval_logger_respects_state_dir(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LEANECON_STATE_DIR", str(tmp_path))

    import eval_logger

    importlib.reload(eval_logger)

    assert eval_logger.LOGS_DIR == tmp_path / "logs"
    assert eval_logger.LOG_FILE == tmp_path / "logs" / "runs.jsonl"
