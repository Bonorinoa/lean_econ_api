"""
lean_verifier.py

Verify Lean 4 source files for LeanEcon.

Full-proof verification writes each candidate to a unique temporary file under
`lean_workspace/LeanEcon/` and compiles that file directly with
`lake env lean <file>`. This avoids the old shared `Proof.lean` bottleneck and
allows concurrent verifier runs without clobbering a tracked module.

The checked-in `Proof.lean` file remains only as a stable fallback write target
for sorry-validation when MCP-backed `lean_run_code` is unavailable.
"""

import logging
import re
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
LEAN_WORKSPACE = PROJECT_ROOT / "lean_workspace"
LEAN_SOURCE_DIR = LEAN_WORKSPACE / "LeanEcon"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
LEGACY_BUILD_FILE = LEAN_SOURCE_DIR / "Proof.lean"
VERIFICATION_FILE_PREFIX = "AgenticProof"


def _ensure_dirs():
    """Create outputs/ directory if it doesn't exist."""
    OUTPUTS_DIR.mkdir(exist_ok=True)


def _sanitize_file_stem(filename: str | None, default: str) -> str:
    """Convert a user-provided label into a Lean-file-friendly stem."""
    candidate = Path(filename).stem if filename else default
    sanitized = re.sub(r"[^A-Za-z0-9_]+", "_", candidate).strip("_")
    if not sanitized:
        sanitized = default
    if not sanitized[0].isalpha():
        sanitized = f"{default}_{sanitized}"
    return sanitized


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def write_lean_file(lean_code: str, filename: str | None = None) -> Path:
    """
    Write Lean 4 source code to the legacy `LeanEcon/Proof.lean` path.

    This helper is kept for the formalizer's sorry-validation fallback, which
    compiles this file directly with `lake env lean` when `lean_run_code` is
    unavailable.

    Args:
        lean_code: Complete .lean file content (must start with `import Mathlib`).
        filename: Ignored (kept for API compatibility).

    Returns:
        Path to lean_workspace/LeanEcon/Proof.lean.
    """
    _ensure_dirs()
    lean_path = LEGACY_BUILD_FILE
    lean_path.write_text(lean_code, encoding="utf-8")
    return lean_path


def write_verification_file(lean_code: str, filename: str | None = None) -> Path:
    """
    Write a unique temporary Lean file for one verifier run.

    Using a fresh filename per run eliminates collisions between concurrent jobs.
    The file is intentionally not part of the import graph; `verify()` compiles
    it directly with `lake env lean`.
    """
    _ensure_dirs()
    stem = _sanitize_file_stem(filename, VERIFICATION_FILE_PREFIX)
    lean_path = LEAN_SOURCE_DIR / f"{stem}_{uuid4().hex[:12]}.lean"
    lean_path.write_text(lean_code, encoding="utf-8")
    return lean_path


def run_direct_lean_check(lean_path: Path, timeout: int = 300) -> dict:
    """
    Compile one Lean file directly with `lake env lean`.

    This checks a standalone file whether or not it is imported from
    `LeanEcon.lean`, which makes it safe for concurrent per-verification temp
    files and for fixed fallback files that are intentionally outside the
    default import graph.

    We intentionally do not use `lean_run_code` here. Local probing on
    2026-03-21 found that complete-proof calls failed with
    "No valid Lean project path found" and became non-responsive after a
    same-session bootstrap attempt, so the direct Lean compiler path is the
    reliable concurrency-safe option for now.
    """
    try:
        relative_path = lean_path.resolve().relative_to(LEAN_WORKSPACE.resolve())
    except ValueError as exc:
        raise ValueError(f"Lean file is outside the workspace: {lean_path}") from exc

    try:
        result = subprocess.run(
            ["lake", "env", "lean", str(relative_path)],
            cwd=str(LEAN_WORKSPACE),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"lake env lean timed out after {timeout}s",
            "errors": [f"Timeout after {timeout}s"],
            "warnings": [],
            "lean_file": str(lean_path),
            "verification_method": "lake_env_lean",
        }
    except FileNotFoundError:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "lake not found on PATH",
            "errors": ["lake executable not found — is Lean 4 installed?"],
            "warnings": [],
            "lean_file": str(lean_path),
            "verification_method": "lake_env_lean",
        }

    combined = result.stdout + "\n" + result.stderr
    errors = _parse_diagnostics(combined, "error")
    warnings = _parse_diagnostics(combined, "warning")

    has_sorry = "declaration uses `sorry`" in combined
    if has_sorry:
        errors.append("Proof contains 'sorry' — not a complete proof.")

    return {
        "success": result.returncode == 0 and not has_sorry,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "errors": errors,
        "warnings": warnings,
        "lean_file": str(lean_path),
        "verification_method": "lake_env_lean",
    }


def verify(
    lean_code: str,
    filename: str | None = None,
    check_axioms: bool = True,
) -> dict:
    """
    Write a unique Lean file and verify it with `lake env lean` in one call.

    This is the main entry point used by pipeline.py.

    Args:
        lean_code: Complete .lean file content.
        filename: Optional base name for the .lean file.
        check_axioms: If True and build succeeds, query lean_verify for axiom info.

    Returns:
        Verification result dict with added keys:
          - lean_code (str): The code that was verified.
          - axiom_info (dict | None): Axiom usage info, if available.
    """
    lean_path = write_verification_file(lean_code, filename)
    try:
        result = run_direct_lean_check(lean_path)
        result["lean_code"] = lean_code

        # Axiom check (only on success, best-effort, file must still exist)
        result["axiom_info"] = None
        if check_axioms and result["success"]:
            try:
                from lean_runner import extract_theorem_name, verify_axioms

                thm_name = extract_theorem_name(lean_code)
                if thm_name:
                    axiom_info = verify_axioms(str(lean_path), thm_name)
                    result["axiom_info"] = axiom_info
                    logger.info(
                        "Axiom check: %s — sound=%s",
                        axiom_info["axioms"],
                        axiom_info["sound"],
                    )
            except Exception as exc:
                logger.warning("Axiom check failed: %s", exc)

        _save_to_outputs(lean_code, lean_path, result)
        return result
    finally:
        lean_path.unlink(missing_ok=True)


def _parse_diagnostics(text: str, level: str) -> list[str]:
    """
    Extract error or warning lines from Lean compiler output.

    The verifier currently sees diagnostics in one of two styles:
      A) Lean text format:
         `LeanEcon/AgenticProof_ab12cd34ef56.lean:5:2: error: message`
      B) Lake summary format:
         `error: LeanEcon/AgenticProof_ab12cd34ef56.lean:5:2: message`

    We capture the message part and up to 3 continuation lines (for goal state).

    Args:
        text: Combined stdout + stderr from the verification command.
        level: "error" or "warning".

    Returns:
        List of diagnostic message strings, each prefixed with location if available.
    """
    lines = text.splitlines()
    results = []
    i = 0
    while i < len(lines):
        line = lines[i]
        msg = None
        location = None

        # Style A: `path:line:col: error: message`  (lean raw text output)
        if f": {level}:" in line:
            parts = line.split(f": {level}:", 1)
            msg = parts[1].strip() if len(parts) > 1 else line.strip()
            location = parts[0].strip()

        # Style B: `error: path:line:col: message`  (lake formatted output)
        elif line.startswith(f"{level}: "):
            rest = line[len(level) + 2 :]
            # Confirm it looks like a path diagnostic (contains .lean:N:M:)
            if re.match(r".*\.lean:\d+:\d+:", rest):
                # Find second colon after .lean:N:
                m = re.match(r"(.*\.lean:\d+:\d+):(.*)", rest)
                if m:
                    location = m.group(1).strip()
                    msg = m.group(2).strip()
            # Also catch bare `error: some message` (no path) like "error: build failed"
            elif level == "error" and not re.match(r".*\.lean", rest):
                # Skip non-diagnostic error lines like "error: build failed"
                pass

        if msg:
            # Grab up to 3 continuation lines (indented goal state, `|` context, `^` markers)
            context_lines = []
            j = i + 1
            while j < len(lines) and j < i + 5:
                next_line = lines[j]
                if (
                    next_line.startswith("  ")
                    or next_line.startswith("| ")
                    or next_line.startswith("^")
                    or next_line.startswith("⊢")
                ):
                    context_lines.append(next_line)
                    j += 1
                else:
                    break
            full_msg = f"{location}: {msg}" if location else msg
            if context_lines:
                full_msg += "\n" + "\n".join(context_lines)
            results.append(full_msg)

        i += 1
    return results


def _save_to_outputs(lean_code: str, lean_path: Path, result: dict):
    """Save the verified .lean file and a brief report to outputs/ with a timestamp."""
    _ensure_dirs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"Proof_{timestamp}"

    # outputs/ is gitignored; these timestamped files are runtime artifacts only.
    output_lean = OUTPUTS_DIR / f"{stem}.lean"
    output_lean.write_text(lean_code, encoding="utf-8")

    # Write a brief verification report
    status = "PASS" if result["success"] else "FAIL"
    report_lines = [
        f"# Verification Report: {stem}",
        f"Status: {status}",
        f"Return code: {result['returncode']}",
        "",
    ]
    if result["errors"]:
        report_lines.append("## Errors")
        for e in result["errors"]:
            report_lines.append(textwrap.indent(e, "  "))
        report_lines.append("")
    if result["warnings"]:
        report_lines.append("## Warnings")
        for w in result["warnings"]:
            report_lines.append(textwrap.indent(w, "  "))
        report_lines.append("")
    method_label = result.get("verification_method", "verifier")
    if result["stdout"].strip():
        report_lines.append(f"## {method_label} stdout")
        report_lines.append("```")
        report_lines.append(result["stdout"].strip())
        report_lines.append("```")
    if result["stderr"].strip():
        report_lines.append(f"## {method_label} stderr")
        report_lines.append("```")
        report_lines.append(result["stderr"].strip())
        report_lines.append("```")

    report_path = OUTPUTS_DIR / f"{stem}_report.md"
    result["output_lean"] = str(output_lean)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")


if __name__ == "__main__":
    print("Run tests via: pytest tests/test_verifier.py")
