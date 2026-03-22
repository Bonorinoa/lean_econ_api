"""Shared fixtures and path setup for LeanEcon tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Ensure src/ and scripts/ are importable
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def pytest_collection_modifyitems(config, items):
    """Auto-skip live tests when MISTRAL_API_KEY is not set."""
    if not os.environ.get("MISTRAL_API_KEY"):
        skip_live = pytest.mark.skip(reason="MISTRAL_API_KEY not set")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)
