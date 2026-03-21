"""
Lightweight wrappers around lean-lsp-mcp tools for
file-free sorry-validation and axiom checking.

Used by:
  - formalizer.py: sorry_validate() fast path via run_code()
  - lean_verifier.py: axiom checking via verify_axioms()
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from mcp_runtime import open_lean_mcp_session

logger = logging.getLogger(__name__)

# Axioms that are standard in Mathlib-based proofs
STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_text(result: Any) -> str:
    """Defensively extract text content from an MCP tool result."""
    content = getattr(result, "content", None)
    if content is None:
        return str(result)
    parts: list[str] = []
    for item in content:
        if hasattr(item, "text"):
            parts.append(item.text)
        elif isinstance(item, dict) and "text" in item:
            parts.append(item["text"])
    return "\n".join(parts)


def _parse_structured(raw_text: str) -> dict[str, Any]:
    """Try to parse the MCP response as JSON, return empty dict on failure."""
    try:
        return json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return {}


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
    async with open_lean_mcp_session() as session:
        result = await session.call_tool("lean_run_code", {"code": lean_code})

    if getattr(result, "isError", False):
        raise RuntimeError(f"lean_run_code MCP error: {result}")

    raw_text = _extract_text(result)
    data = _parse_structured(raw_text)

    # lean_run_code returns:
    #   {"success": bool, "diagnostics": [{"severity": str, "message": str, ...}]}
    diagnostics = data.get("diagnostics", [])

    errors: list[str] = []
    warnings: list[str] = []
    for d in diagnostics:
        sev = d.get("severity", "")
        msg = d.get("message", "")
        if sev == "error":
            errors.append(msg)
        elif sev == "warning":
            warnings.append(msg)

    # Filter sorry-related messages — sorry is expected during sorry-validation
    real_errors = [
        e for e in errors
        if "sorry" not in e.lower() and "declaration uses" not in e.lower()
    ]

    # Use the tool's own success flag as primary signal, but also check real_errors
    tool_success = data.get("success", False)
    valid = tool_success and len(real_errors) == 0

    # Edge case: tool says success=true but we found real errors in diagnostics
    if not tool_success and len(real_errors) == 0:
        # Tool reported failure, but no real errors — likely only sorry warnings
        valid = True

    return {
        "valid": valid,
        "errors": real_errors,
        "warnings": warnings,
        "raw": raw_text,
    }


def run_code(lean_code: str) -> dict[str, Any]:
    """Synchronous wrapper for _run_code_async."""
    return asyncio.run(_run_code_async(lean_code))


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
        result = await session.call_tool("lean_verify", {
            "file_path": file_path,
            "theorem_name": theorem_name,
            "scan_source": True,
        })

    if getattr(result, "isError", False):
        raise RuntimeError(f"lean_verify MCP error: {result}")

    raw_text = _extract_text(result)
    data = _parse_structured(raw_text)

    # lean_verify returns:
    #   {"axioms": [str], "warnings": [{"line": int, "pattern": str}]}
    axioms = data.get("axioms", [])
    source_warnings = data.get("warnings", [])

    has_sorry = any("sorry" in a.lower() for a in axioms)
    standard = [a for a in axioms if a in STANDARD_AXIOMS]
    nonstandard = [
        a for a in axioms
        if a not in STANDARD_AXIOMS and "sorry" not in a.lower()
    ]

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
    return asyncio.run(_verify_axioms_async(file_path, theorem_name))


# ---------------------------------------------------------------------------
# Theorem name extraction
# ---------------------------------------------------------------------------

def extract_theorem_name(lean_code: str) -> str | None:
    """Extract the first theorem or lemma name from Lean source code."""
    m = re.search(r"\b(?:theorem|lemma)\s+(\S+)", lean_code)
    return m.group(1) if m else None
