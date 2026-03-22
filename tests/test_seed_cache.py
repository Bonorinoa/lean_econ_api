"""Tests for scripts/seed_cache.py."""

from __future__ import annotations

import seed_cache


class _DummyCache:
    def __init__(self) -> None:
        self.entries: list[tuple[str, dict]] = []

    def put(self, claim_text: str, result: dict) -> None:
        self.entries.append((claim_text, result))

    @property
    def size(self) -> int:
        return len(self.entries)


def test_seed_cache_main_seeds_only_pass_examples(tmp_path, monkeypatch, capsys) -> None:
    examples_dir = tmp_path / "examples"
    examples_dir.mkdir()

    (examples_dir / "demo_pass.lean").write_text(
        "theorem demo : True := by trivial\n", encoding="utf-8"
    )
    (examples_dir / "demo_pass_report.md").write_text("Verified example", encoding="utf-8")
    (examples_dir / "demo_fail.lean").write_text(
        "theorem demo_fail : False := by sorry\n", encoding="utf-8"
    )

    cache = _DummyCache()
    monkeypatch.setattr(seed_cache, "EXAMPLES_DIR", examples_dir)
    monkeypatch.setattr(seed_cache, "result_cache", cache)

    seed_cache.main()

    output = capsys.readouterr().out
    assert "Cached: demo_pass.lean" in output
    assert "Cache size: 1" in output
    assert len(cache.entries) == 1
    _, payload = cache.entries[0]
    assert payload["success"] is True
    assert payload["phase"] == "verified"
