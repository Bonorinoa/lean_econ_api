"""Shared helpers for trace-oriented evaluation metrics."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

WRITE_TOOL_NAMES = {"apply_tactic"}
DIAGNOSTIC_TOOL_NAMES = {"lean_diagnostic_messages"}
SEARCH_TOOL_NAMES = {
    "lean_multi_attempt",
    "lean_code_actions",
    "lean_state_search",
    "lean_hammer_premise",
}


def load_jsonl_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Load JSONL records while tolerating malformed lines."""
    records: list[dict[str, Any]] = []
    malformed = 0

    if not path.is_file():
        return records, malformed

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(payload, dict):
            records.append(payload)
        else:
            malformed += 1
    return records, malformed


def extract_tactic_heads(tactic_text: str) -> list[str]:
    """Extract first-token tactic heads from a Lean tactic block."""
    heads: list[str] = []
    for raw_line in tactic_text.splitlines():
        line = raw_line.strip()
        if not line or line in {"by", "{", "}"} or line.startswith("--"):
            continue
        line = line.lstrip("·|").strip()
        if line.startswith("case "):
            continue
        match = re.match(r"([A-Za-z_][\w'!?]*)", line)
        if match:
            heads.append(match.group(1))
    return heads


def _proving_block(record: dict[str, Any]) -> dict[str, Any]:
    proving = record.get("proving")
    if isinstance(proving, dict):
        return proving
    return record


def _verification_success(record: dict[str, Any]) -> bool:
    verification = record.get("verification")
    if isinstance(verification, dict):
        return bool(verification.get("success"))
    return bool(record.get("success"))


def _verification_errors(record: dict[str, Any]) -> list[str]:
    verification = record.get("verification")
    if isinstance(verification, dict):
        errors = verification.get("errors", [])
        if isinstance(errors, list):
            return [str(item) for item in errors]
    errors = record.get("errors", [])
    if isinstance(errors, list):
        return [str(item) for item in errors]
    return []


def tool_trace_entries(record: dict[str, Any]) -> list[dict[str, Any]]:
    proving = _proving_block(record)
    tool_trace = proving.get("tool_trace", [])
    if isinstance(tool_trace, list):
        return [entry for entry in tool_trace if isinstance(entry, dict)]
    return []


def tactic_calls(record: dict[str, Any]) -> list[dict[str, Any]]:
    proving = _proving_block(record)
    calls = proving.get("tactic_calls", [])
    if isinstance(calls, list):
        return [entry for entry in calls if isinstance(entry, dict)]
    return []


def total_tool_calls(record: dict[str, Any]) -> int:
    return sum(1 for entry in tool_trace_entries(record) if entry.get("type") == "tool_call")


def blocked_tool_calls(record: dict[str, Any]) -> int:
    return sum(1 for entry in tool_trace_entries(record) if entry.get("blocked") is True)


def tool_calls_by_name(record: dict[str, Any], names: set[str]) -> int:
    return sum(1 for entry in tool_trace_entries(record) if entry.get("tool_name") in names)


def successful_tactic_applications(record: dict[str, Any]) -> int:
    return sum(1 for entry in tactic_calls(record) if entry.get("successful") is True)


def tactic_depth(record: dict[str, Any]) -> int | None:
    if not _verification_success(record):
        return None

    proving = _proving_block(record)
    proof_tactics = str(proving.get("proof_tactics") or record.get("proof_tactics") or "")
    heads = extract_tactic_heads(proof_tactics)
    if not heads:
        heads = [
            str(entry.get("tactic_preview") or entry.get("tactic") or "")
            for entry in tactic_calls(record)
            if entry.get("successful") is True
        ]
        parsed_heads: list[str] = []
        for head in heads:
            parsed_heads.extend(extract_tactic_heads(head))
        heads = parsed_heads
    unique_heads = {head for head in heads if head}
    return len(unique_heads)


def failed_kernel_errors(record: dict[str, Any]) -> list[str]:
    if _verification_success(record):
        return []

    errors: list[str] = []
    for entry in tool_trace_entries(record):
        kernel_errors = entry.get("kernel_errors", [])
        if isinstance(kernel_errors, list):
            errors.extend(str(item) for item in kernel_errors if str(item).strip())

    if errors:
        return errors
    return _verification_errors(record)


def aggregate_trace_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the deep-trace metrics requested by the evaluation harness."""
    total_tool_call_count = sum(total_tool_calls(record) for record in records)
    successful_tactic_count = sum(successful_tactic_applications(record) for record in records)
    blocked_tool_call_count = sum(blocked_tool_calls(record) for record in records)
    write_tool_call_count = sum(tool_calls_by_name(record, WRITE_TOOL_NAMES) for record in records)
    diagnostic_tool_call_count = sum(
        tool_calls_by_name(record, DIAGNOSTIC_TOOL_NAMES) for record in records
    )
    search_tool_call_count = sum(
        tool_calls_by_name(record, SEARCH_TOOL_NAMES) for record in records
    )

    tactic_depths = [depth for record in records if (depth := tactic_depth(record)) is not None]

    error_counter: Counter[str] = Counter()
    for record in records:
        error_counter.update(failed_kernel_errors(record))

    tool_call_efficiency = 0.0
    if total_tool_call_count:
        tool_call_efficiency = successful_tactic_count / total_tool_call_count
    tool_call_waste_ratio = 1.0 - tool_call_efficiency if total_tool_call_count else 0.0

    average_tactic_depth = 0.0
    if tactic_depths:
        average_tactic_depth = sum(tactic_depths) / len(tactic_depths)

    return {
        "runs_considered": len(records),
        "total_tool_calls": total_tool_call_count,
        "successful_tactic_applications": successful_tactic_count,
        "tool_call_efficiency": round(tool_call_efficiency, 3),
        "tool_call_waste_ratio": round(tool_call_waste_ratio, 3),
        "blocked_tool_calls": blocked_tool_call_count,
        "write_tool_calls": write_tool_call_count,
        "diagnostic_tool_calls": diagnostic_tool_call_count,
        "search_tool_calls": search_tool_call_count,
        "successful_proofs_considered": len(tactic_depths),
        "tactic_depth_average": round(average_tactic_depth, 3),
        "error_frequency": dict(error_counter.most_common()),
    }


def render_trace_metrics(metrics: dict[str, Any]) -> str:
    """Render a compact human-readable summary of aggregate trace metrics."""
    lines = [
        f"Runs parsed: {metrics.get('runs_considered', 0)}",
        (
            "Tool Call Efficiency: "
            f"{metrics.get('tool_call_efficiency', 0.0):.3f} "
            f"({metrics.get('successful_tactic_applications', 0)}/"
            f"{metrics.get('total_tool_calls', 0)})"
        ),
        f"Tool Call Waste Ratio: {metrics.get('tool_call_waste_ratio', 0.0):.3f}",
        (
            "Tool Mix: "
            f"{metrics.get('write_tool_calls', 0)} writes, "
            f"{metrics.get('diagnostic_tool_calls', 0)} diagnostics, "
            f"{metrics.get('search_tool_calls', 0)} search, "
            f"{metrics.get('blocked_tool_calls', 0)} blocked"
        ),
        (
            "Average Tactic Depth: "
            f"{metrics.get('tactic_depth_average', 0.0):.3f} "
            f"across {metrics.get('successful_proofs_considered', 0)} successful proofs"
        ),
        "Top Lean Kernel Errors:",
    ]

    error_frequency = metrics.get("error_frequency", {})
    if not error_frequency:
        lines.append("  (none)")
    else:
        for message, count in list(error_frequency.items())[:10]:
            lines.append(f"  - {count}x {message}")

    return "\n".join(lines)
