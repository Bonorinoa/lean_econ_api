"""Shared parsing helpers for Lean/MCP diagnostics and JSON payloads."""

from __future__ import annotations

import json
import re
from typing import Any


def strip_markdown_fences(text: str) -> str:
    """Remove simple markdown fences around model output."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
    if stripped.endswith("```"):
        stripped = stripped[:-3]
    return stripped.strip()


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of a JSON object from model output."""
    stripped = strip_markdown_fences(text)
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def extract_mcp_text(result: Any) -> str:
    """Defensively extract text content from an MCP tool result."""
    content = getattr(result, "content", None)
    if content is None:
        return str(result)
    parts: list[str] = []
    for item in content:
        text = getattr(item, "text", None)
        if text is not None:
            parts.append(str(text))
        elif isinstance(item, dict) and "text" in item:
            parts.append(str(item["text"]))
    return "\n".join(part for part in parts if part).strip()


def extract_json_payload(value: Any) -> dict[str, Any] | None:
    """Parse JSON-like MCP payloads embedded as strings, dicts, or content lists."""
    payload = value
    if isinstance(payload, str):
        stripped = strip_markdown_fences(payload)
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return extract_json_object(stripped)
        if isinstance(decoded, dict):
            return decoded
        if isinstance(decoded, list) and decoded:
            first = decoded[0]
            if isinstance(first, dict):
                text = first.get("text")
                if isinstance(text, str):
                    return extract_json_object(text)
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            text = first.get("text")
            if isinstance(text, str):
                return extract_json_object(text)
    return None


def normalize_structured_diagnostics(
    payload: dict[str, Any],
    *,
    result_key: str | None = None,
) -> dict[str, Any]:
    """Normalize structured Lean diagnostics into consistent error/warning lists."""
    root = payload
    if result_key and isinstance(payload.get(result_key), dict):
        root = payload[result_key]

    items = root.get("items", [])
    if not isinstance(items, list):
        items = []

    errors: list[str] = []
    warnings: list[str] = []
    normalized_items: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        message = str(item.get("message", "")).strip()
        line = item.get("line")
        prefix = f"line {line}: " if line else ""
        normalized = {
            "severity": item.get("severity"),
            "message": message,
            "line": line,
            "column": item.get("column"),
        }
        normalized_items.append(normalized)
        if item.get("severity") == "error":
            errors.append(prefix + message)
        elif item.get("severity") == "warning":
            warnings.append(prefix + message)

    return {
        "success": bool(root.get("success", False)),
        "errors": errors,
        "warnings": warnings,
        "items": normalized_items,
    }


def parse_plain_lean_diagnostics(text: str, level: str) -> list[str]:
    """Extract error or warning lines from Lean compiler output."""
    lines = text.splitlines()
    results: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        msg = None
        location = None

        if f": {level}:" in line:
            parts = line.split(f": {level}:", 1)
            msg = parts[1].strip() if len(parts) > 1 else line.strip()
            location = parts[0].strip()
        elif line.startswith(f"{level}: "):
            rest = line[len(level) + 2 :]
            if re.match(r".*\.lean:\d+:\d+:", rest):
                match = re.match(r"(.*\.lean:\d+:\d+):(.*)", rest)
                if match:
                    location = match.group(1).strip()
                    msg = match.group(2).strip()
            elif level == "error" and not re.match(r".*\.lean", rest):
                msg = None

        if msg is not None:
            continuation: list[str] = []
            next_index = index + 1
            while next_index < len(lines) and len(continuation) < 3:
                candidate = lines[next_index]
                stripped = candidate.strip()
                if not stripped:
                    break
                if ": error:" in candidate or ": warning:" in candidate:
                    break
                if candidate.startswith("error: ") or candidate.startswith("warning: "):
                    break
                continuation.append(stripped)
                next_index += 1
            rendered = f"{location}: {msg}" if location else msg
            if continuation:
                rendered = rendered + "\n" + "\n".join(continuation)
            results.append(rendered)
            index = next_index
            continue

        index += 1

    return results
