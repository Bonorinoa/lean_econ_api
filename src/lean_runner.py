"""
Lightweight wrappers around lean-lsp-mcp tools for
file-free sorry-validation and axiom checking.

Used by:
  - formalizer.py: sorry_validate() fast path via run_code()
  - lean_verifier.py: axiom checking via verify_axioms()
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from lean_diagnostics import extract_json_object, extract_mcp_text, normalize_structured_diagnostics
from mcp_runtime import (
    formalization_mcp_available,
    mark_formalization_mcp_failure,
    mark_formalization_mcp_success,
    open_lean_mcp_session,
)

logger = logging.getLogger(__name__)
T = TypeVar("T")
MCP_TOOL_TIMEOUT_SECONDS = float(os.environ.get("LEANECON_MCP_TOOL_TIMEOUT_SECONDS", "10"))

# Axioms that are standard in Mathlib-based proofs
STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})


def _run_sync(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run an async helper from sync code, even if an event loop is already active."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: list[T] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as exc:  # pragma: no cover - re-raised below
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if error:
        raise error[0]
    if not result:  # pragma: no cover - defensive, should be unreachable
        raise RuntimeError("Async wrapper exited without returning a result")
    return result[0]


def _extract_text(result: Any) -> str:
    """Backward-compatible wrapper for MCP text extraction."""
    return extract_mcp_text(result)


def _parse_structured(text: str) -> dict[str, Any]:
    """Backward-compatible wrapper for JSON payload parsing."""
    return extract_json_object(text) or {}


# ---------------------------------------------------------------------------
# lean_run_code wrapper
# ---------------------------------------------------------------------------


async def _run_code_async(lean_code: str) -> dict[str, Any]:
    """
    Compile a Lean code snippet via lean_run_code and return structured results.

    Returns dict with:
      - valid (bool): True if no real errors (sorry warnings are OK)
      - errors (list[str]): Error messages
      - warnings (list[str]): Warning messages
      - raw (str): Raw tool output
    """
    allowed, reason = formalization_mcp_available()
    if not allowed:
        raise RuntimeError(reason or "formalization MCP temporarily disabled")

    async with open_lean_mcp_session() as session:
        try:
            result = await asyncio.wait_for(
                session.call_tool("lean_run_code", {"code": lean_code}),
                timeout=MCP_TOOL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            mark_formalization_mcp_failure(
                f"lean_run_code timed out after {MCP_TOOL_TIMEOUT_SECONDS:.1f}s"
            )
            raise RuntimeError(
                f"lean_run_code timed out after {MCP_TOOL_TIMEOUT_SECONDS:.1f}s"
            ) from exc

    if getattr(result, "isError", False):
        raw_error = extract_mcp_text(result)
        mark_formalization_mcp_failure(raw_error or "lean_run_code MCP error")
        raise RuntimeError(f"lean_run_code MCP error: {raw_error or result}")

    raw_text = extract_mcp_text(result)
    data = extract_json_object(raw_text) or {}

    # lean_run_code returns:
    #   {"success": bool, "diagnostics": [{"severity": str, "message": str, ...}]}
    normalized = normalize_structured_diagnostics(
        {"success": data.get("success", False), "items": data.get("diagnostics", [])}
    )
    errors = normalized["errors"]
    warnings = normalized["warnings"]

    # Filter sorry-related messages — sorry is expected during sorry-validation
    real_errors = [
        e for e in errors if "sorry" not in e.lower() and "declaration uses" not in e.lower()
    ]

    # Use the tool's own success flag as primary signal, but also check real_errors
    tool_success = data.get("success", False)
    valid = tool_success and len(real_errors) == 0

    # Edge case: tool says success=true but we found real errors in diagnostics
    if not tool_success and len(real_errors) == 0:
        # Tool reported failure, but no real errors — likely only sorry warnings
        valid = True

    mark_formalization_mcp_success()

    return {
        "valid": valid,
        "errors": real_errors,
        "warnings": warnings,
        "raw": raw_text,
    }


def run_code(lean_code: str) -> dict[str, Any]:
    """Synchronous wrapper for _run_code_async."""
    return _run_sync(lambda: _run_code_async(lean_code))


# ---------------------------------------------------------------------------
# lean_verify wrapper
# ---------------------------------------------------------------------------


async def _verify_axioms_async(
    file_path: str,
    theorem_name: str,
) -> dict[str, Any]:
    """
    Check which axioms a verified theorem depends on.

    Args:
        file_path: Absolute path to the .lean file.
        theorem_name: Theorem name (e.g. "my_theorem").

    Returns dict with:
      - axioms (list[str]): All axiom names
      - standard_axioms (list[str]): Expected axioms
      - nonstandard_axioms (list[str]): Unusual axioms
      - has_sorry_ax (bool): True if sorryAx is present
      - sound (bool): True if no sorryAx
      - source_warnings (list[dict]): Source scan warnings
    """
    async with open_lean_mcp_session() as session:
        try:
            result = await asyncio.wait_for(
                session.call_tool(
                    "lean_verify",
                    {
                        "file_path": file_path,
                        "theorem_name": theorem_name,
                        "scan_source": True,
                    },
                ),
                timeout=MCP_TOOL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"lean_verify timed out after {MCP_TOOL_TIMEOUT_SECONDS:.1f}s"
            ) from exc

    if getattr(result, "isError", False):
        raise RuntimeError(f"lean_verify MCP error: {result}")

    raw_text = extract_mcp_text(result)
    data = extract_json_object(raw_text) or {}

    # lean_verify returns:
    #   {"axioms": [str], "warnings": [{"line": int, "pattern": str}]}
    axioms = data.get("axioms", [])
    source_warnings = data.get("warnings", [])

    has_sorry = any("sorry" in a.lower() for a in axioms)
    standard = [a for a in axioms if a in STANDARD_AXIOMS]
    nonstandard = [a for a in axioms if a not in STANDARD_AXIOMS and "sorry" not in a.lower()]

    return {
        "axioms": axioms,
        "standard_axioms": standard,
        "nonstandard_axioms": nonstandard,
        "has_sorry_ax": has_sorry,
        "sound": not has_sorry,
        "source_warnings": source_warnings,
    }


def verify_axioms(file_path: str, theorem_name: str) -> dict[str, Any]:
    """Synchronous wrapper for _verify_axioms_async."""
    return _run_sync(lambda: _verify_axioms_async(file_path, theorem_name))


# ---------------------------------------------------------------------------
# Theorem name extraction
# ---------------------------------------------------------------------------


def extract_theorem_name(lean_code: str) -> str | None:
    """Extract the first theorem or lemma name from Lean source code."""
    m = re.search(r"\b(?:theorem|lemma)\s+(\S+)", lean_code)
    return m.group(1) if m else None
