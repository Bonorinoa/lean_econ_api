"""Tests for result_cache.py — thread-safe verified result cache."""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

from result_cache import ResultCache, MAX_CACHE_SIZE


def _make_cache(tmpdir: str) -> ResultCache:
    return ResultCache(cache_file=Path(tmpdir) / "cache.json")


def test_put_and_get() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = _make_cache(tmpdir)
        result = {"success": True, "lean_code": "theorem t : True := by trivial"}
        cache.put("1 + 1 = 2", result)
        got = cache.get("1 + 1 = 2")
        assert got is not None
        assert got["success"] is True
        assert got["lean_code"] == result["lean_code"]


def test_put_skips_failures() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = _make_cache(tmpdir)
        cache.put("bad claim", {"success": False, "errors": ["failed"]})
        assert cache.get("bad claim") is None
        assert cache.size == 0


def test_get_returns_none_for_missing() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = _make_cache(tmpdir)
        assert cache.get("never inserted") is None


def test_lru_eviction() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = _make_cache(tmpdir)
        for i in range(MAX_CACHE_SIZE + 5):
            cache.put(f"claim_{i}", {"success": True, "id": i})
        assert cache.size == MAX_CACHE_SIZE
        # First few should have been evicted
        assert cache.get("claim_0") is None
        # Last entry should still be present
        assert cache.get(f"claim_{MAX_CACHE_SIZE + 4}") is not None


def test_cache_key_normalization() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = _make_cache(tmpdir)
        cache.put("  hello world  ", {"success": True})
        assert cache.get("hello world") is not None
        assert cache.get("  hello world  ") is not None


def test_persistence_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / "cache.json"
        cache1 = ResultCache(cache_file=cache_file)
        cache1.put("persisted claim", {"success": True, "data": 42})
        assert cache_file.is_file()

        # Create a new cache from the same file
        cache2 = ResultCache(cache_file=cache_file)
        got = cache2.get("persisted claim")
        assert got is not None
        assert got["data"] == 42


def test_clear() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = _make_cache(tmpdir)
        cache.put("claim_a", {"success": True})
        cache.put("claim_b", {"success": True})
        assert cache.size == 2
        cache.clear()
        assert cache.size == 0
        assert cache.get("claim_a") is None


def test_thread_safety() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = _make_cache(tmpdir)
        errors: list[Exception] = []

        def writer(thread_id: int) -> None:
            try:
                for i in range(20):
                    cache.put(f"thread_{thread_id}_claim_{i}", {"success": True, "tid": thread_id})
            except Exception as exc:
                errors.append(exc)

        def reader(thread_id: int) -> None:
            try:
                for i in range(20):
                    cache.get(f"thread_{thread_id}_claim_{i}")
            except Exception as exc:
                errors.append(exc)

        threads = []
        for tid in range(4):
            threads.append(threading.Thread(target=writer, args=(tid,)))
            threads.append(threading.Thread(target=reader, args=(tid,)))

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"Thread safety errors: {errors}"
        assert cache.size > 0


def test_corrupted_cache_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / "cache.json"
        cache_file.write_text("not valid json", encoding="utf-8")
        cache = ResultCache(cache_file=cache_file)
        assert cache.size == 0  # Gracefully recovers
