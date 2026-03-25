"""
proof_file_controller.py

Local-first controller for a single MCP-driven working Lean proof file.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from mcp_runtime import LEAN_WORKSPACE, lean_workspace_relative_path

DEFAULT_WORKING_FILE_BASENAME = "AgenticProof"
DEFAULT_HEADER = "import Mathlib\nopen Real\n\n"
TACTIC_REGION_BEGIN = "-- LEANECON_AGENTIC_TACTICS_BEGIN"
TACTIC_REGION_END = "-- LEANECON_AGENTIC_TACTICS_END"
_SORRY_LINE_RE = re.compile(r"(?m)^([ \t]*)sorry\b[^\n]*$")
_INLINE_SORRY_LINE_RE = re.compile(r"(?m)^([ \t]*)(.*?:=\s*by)\s+sorry\b([^\n]*)$")


def _default_working_file() -> Path:
    """
    Allocate a unique working file for one agentic proving run.

    The old fixed `AgenticProof.lean` path caused concurrent runs to overwrite
    each other. A unique default keeps MCP-visible file paths isolated per job.
    """
    suffix = uuid4().hex[:12]
    return LEAN_WORKSPACE / "LeanEcon" / f"{DEFAULT_WORKING_FILE_BASENAME}_{suffix}.lean"


@dataclass(frozen=True)
class ProofCheckpoint:
    """In-memory snapshot of a known-good controller state."""

    label: str
    tactic_block: str
    lean_code: str


class ProofFileController:
    """Own one working Lean file and one editable tactic region."""

    def __init__(self, working_file: Path | None = None):
        self._working_file = working_file or _default_working_file()
        self._theorem_with_sorry = ""
        self._prefix = ""
        self._suffix = ""
        self._indent = "  "
        self._current_tactic_block = "sorry"
        self._current_lean_code = ""
        self._checkpoints: list[ProofCheckpoint] = []

    @property
    def working_file(self) -> Path:
        return self._working_file

    @property
    def mcp_file_path(self) -> str:
        return lean_workspace_relative_path(self._working_file)

    @property
    def theorem_with_sorry(self) -> str:
        return self._theorem_with_sorry

    @property
    def current_tactic_block(self) -> str:
        self._require_initialized()
        return self._current_tactic_block

    @property
    def current_lean_code(self) -> str:
        self._require_initialized()
        return self._current_lean_code

    @property
    def checkpoints(self) -> tuple[ProofCheckpoint, ...]:
        return tuple(self._checkpoints)

    @property
    def theorem_name(self) -> str | None:
        self._require_initialized()
        match = re.search(r"(?m)^\s*(theorem|lemma|example)\s+([^\s(:]+)", self._current_lean_code)
        if match:
            return match.group(2)
        return None

    @property
    def goal_query_line(self) -> int:
        self._require_initialized()
        return self._line_number_containing(":= by")

    @property
    def tactic_region_start_line(self) -> int:
        self._require_initialized()
        return self._line_number_containing(TACTIC_REGION_BEGIN) + 1

    def initialize(self, theorem_with_sorry: str, checkpoint_label: str = "initial") -> str:
        """
        Normalize the theorem input, create the working file, and checkpoint it.
        """
        normalized = self._normalize_theorem_input(theorem_with_sorry)
        match = _SORRY_LINE_RE.search(normalized)
        if not match:
            raise ValueError("theorem_with_sorry must contain a standalone `sorry` line")

        self._theorem_with_sorry = normalized
        self._prefix = normalized[: match.start()]
        self._suffix = normalized[match.end() :]
        self._indent = match.group(1) or "  "
        self._current_tactic_block = "sorry"
        self._current_lean_code = self._render_current_code()
        self._write_current_code()

        self._checkpoints = []
        self.save_checkpoint(checkpoint_label)
        return self._current_lean_code

    def replace_tactic_block(
        self,
        tactic_block: str,
        checkpoint_label: str | None = None,
    ) -> str:
        """Replace the editable tactic region and rewrite the working file."""
        self._require_initialized()
        self._current_tactic_block = self._normalize_tactic_block(tactic_block)
        self._current_lean_code = self._render_current_code()
        self._write_current_code()
        if checkpoint_label:
            self.save_checkpoint(checkpoint_label)
        return self._current_lean_code

    def append_tactic_block(
        self,
        tactic_fragment: str,
        checkpoint_label: str | None = None,
    ) -> str:
        """Append one tactic fragment to the current editable region."""
        self._require_initialized()
        fragment = self._normalize_tactic_block(tactic_fragment)
        if self._current_tactic_block.strip() == "sorry":
            combined = fragment
        else:
            combined = f"{self._current_tactic_block.rstrip()}\n{fragment}"
        return self.replace_tactic_block(combined, checkpoint_label=checkpoint_label)

    def save_checkpoint(self, label: str) -> ProofCheckpoint:
        """Save the current in-memory state as a named checkpoint."""
        self._require_initialized()
        checkpoint = ProofCheckpoint(
            label=label,
            tactic_block=self._current_tactic_block,
            lean_code=self._current_lean_code,
        )
        self._checkpoints.append(checkpoint)
        return checkpoint

    def restore_last_good_checkpoint(self) -> str:
        """Restore the most recent checkpoint and rewrite the working file."""
        self._require_initialized()
        if not self._checkpoints:
            raise RuntimeError("No checkpoints are available to restore")

        checkpoint = self._checkpoints[-1]
        self._current_tactic_block = checkpoint.tactic_block
        self._current_lean_code = checkpoint.lean_code
        self._write_current_code()
        return self._current_lean_code

    def cleanup(self) -> None:
        """Delete the working file if it exists."""
        if self._working_file.exists():
            self._working_file.unlink()

    def _normalize_theorem_input(self, theorem_with_sorry: str) -> str:
        code = theorem_with_sorry.strip()
        if not code.startswith("import"):
            code = DEFAULT_HEADER + code
        code = _INLINE_SORRY_LINE_RE.sub(
            lambda match: (
                f"{match.group(1)}{match.group(2)}\n{match.group(1)}  sorry{match.group(3)}"
            ),
            code,
            count=1,
        )
        return code.rstrip() + "\n"

    def _normalize_tactic_block(self, tactic_block: str) -> str:
        cleaned = textwrap.dedent(tactic_block).strip()
        if not cleaned:
            raise ValueError("Tactic block cannot be empty")
        return cleaned

    def _render_current_code(self) -> str:
        region = "\n".join(
            [
                f"{self._indent}{TACTIC_REGION_BEGIN}",
                self._indent_block(self._current_tactic_block),
                f"{self._indent}{TACTIC_REGION_END}",
            ]
        )
        return f"{self._prefix}{region}{self._suffix}"

    def _indent_block(self, text: str) -> str:
        lines = text.splitlines()
        return "\n".join(f"{self._indent}{line}" if line.strip() else line for line in lines)

    def _write_current_code(self) -> None:
        self._working_file.parent.mkdir(parents=True, exist_ok=True)
        self._working_file.write_text(self._current_lean_code, encoding="utf-8")

    def _line_number_containing(self, needle: str) -> int:
        for index, line in enumerate(self._current_lean_code.splitlines(), start=1):
            if needle in line:
                return index
        raise RuntimeError(f"Could not find line containing {needle!r}")

    def _require_initialized(self) -> None:
        if not self._current_lean_code:
            raise RuntimeError("ProofFileController is not initialized yet")
