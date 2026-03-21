"""
Prover backend protocol and registry.

Backends encapsulate SDK-specific proving logic so the pipeline can dispatch
without depending on a single prover implementation module.
"""

from __future__ import annotations

import importlib
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProverBackend(Protocol):
    """Protocol every proving backend must satisfy."""

    @property
    def name(self) -> str:
        """Human-readable backend name."""
        ...

    def prove(
        self,
        theorem_with_sorry: str,
        on_log: Any | None = None,
    ) -> dict[str, Any]:
        """Attempt to prove the given theorem and return a normalized backend dict."""
        ...


PROVER_REGISTRY: dict[str, type[Any]] = {}
_BUILTINS_LOADED = False


def register_prover(name: str):
    """Decorator used by prover modules to register backend classes."""

    def decorator(cls):
        PROVER_REGISTRY[name] = cls
        return cls

    return decorator


def _load_builtin_provers() -> None:
    """Import built-in prover modules for registration side effects."""
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    importlib.import_module("agentic_prover")
    _BUILTINS_LOADED = True


def get_prover(name: str = "leanstral") -> ProverBackend:
    """Instantiate a prover backend by name."""
    _load_builtin_provers()
    if name not in PROVER_REGISTRY:
        available = ", ".join(sorted(PROVER_REGISTRY.keys()))
        raise ValueError(f"Unknown prover backend '{name}'. Available: {available}")
    return PROVER_REGISTRY[name]()


_load_builtin_provers()
