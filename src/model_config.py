"""Centralized model/runtime configuration for LeanEcon."""

from __future__ import annotations

import os

DEFAULT_LEANSTRAL_MODEL = "labs-leanstral-2603"
DEFAULT_CONFIG_VERSION = "2026-03-23"

LEANSTRAL_MODEL = (
    os.environ.get("LEANECON_MODEL", DEFAULT_LEANSTRAL_MODEL).strip() or DEFAULT_LEANSTRAL_MODEL
)
CONFIG_VERSION = (
    os.environ.get("LEANECON_CONFIG_VERSION", DEFAULT_CONFIG_VERSION).strip()
    or DEFAULT_CONFIG_VERSION
)


def model_fingerprint(*, scope: str, extras: dict[str, object] | None = None) -> str:
    """Build a stable cache/log fingerprint for model-driven work."""
    payload: dict[str, object] = {
        "scope": scope,
        "model": LEANSTRAL_MODEL,
        "config_version": CONFIG_VERSION,
    }
    if extras:
        payload.update(extras)
    normalized = ",".join(f"{key}={payload[key]}" for key in sorted(payload))
    return normalized
