"""Tests for scripts/generate_preamble_catalog.py."""

from __future__ import annotations

import generate_preamble_catalog


def test_build_catalog_markdown_includes_known_entry() -> None:
    markdown = generate_preamble_catalog.build_catalog_markdown()

    assert markdown.startswith("# LeanEcon Preamble Catalog")
    assert "`crra_utility`" in markdown
    assert "LeanEcon/Preamble/Consumer/CRRAUtility.lean" in markdown


def test_main_writes_catalog(tmp_path, monkeypatch) -> None:
    output_path = tmp_path / "PREAMBLE_CATALOG.md"
    monkeypatch.setattr(generate_preamble_catalog, "OUTPUT_FILE", output_path)

    exit_code = generate_preamble_catalog.main()

    assert exit_code == 0
    assert output_path.read_text(encoding="utf-8").startswith("# LeanEcon Preamble Catalog")
