"""
Result cache for verified claims.

Caches successful pipeline results keyed by claim hash. Returns cached results
instantly. Only caches verified successes; failures are never cached.

Storage: JSON file at `data/verified_cache.json` by default, or
`${LEANECON_STATE_DIR}/data/verified_cache.json` when `LEANECON_STATE_DIR`
is set. Loaded into memory at startup.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("leanecon.cache")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_CACHE_SIZE = 500


def _state_dir() -> Path:
    configured = os.environ.get("LEANECON_STATE_DIR")
    if configured:
        return Path(configured).expanduser()
    return PROJECT_ROOT


CACHE_DIR = _state_dir() / "data"
CACHE_FILE = CACHE_DIR / "verified_cache.json"


class ResultCache:
    """Thread-safe result cache backed by a JSON file."""

    def __init__(self, cache_file: Path | None = None):
        self._cache_file = cache_file or CACHE_FILE
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not self._cache_file.is_file():
            return
        try:
            with self._cache_file.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                self._cache = loaded
                logger.info("Loaded %s cached results", len(self._cache))
            else:
                logger.warning("Cache load failed: expected dict, got %s", type(loaded).__name__)
                self._cache = {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Cache load failed: %s", exc)
            self._cache = {}

    def _save(self) -> None:
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with self._cache_file.open("w", encoding="utf-8") as handle:
                json.dump(self._cache, handle, indent=2, default=str)
        except OSError as exc:
            logger.warning("Cache save failed: %s", exc)

    @staticmethod
    def _make_key(claim_text: str) -> str:
        normalized = claim_text.strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]

    def get(self, claim_text: str) -> dict[str, Any] | None:
        key = self._make_key(claim_text)
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            logger.info("Cache hit for key %s", key)
            return copy.deepcopy(entry.get("result"))

    def put(self, claim_text: str, result: dict[str, Any]) -> None:
        if not result.get("success"):
            return

        key = self._make_key(claim_text)
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            elif len(self._cache) >= MAX_CACHE_SIZE:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]

            self._cache[key] = {
                "claim_text": claim_text.strip(),
                "result": copy.deepcopy(result),
            }
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._cache = {}
            self._save()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)


result_cache = ResultCache()
