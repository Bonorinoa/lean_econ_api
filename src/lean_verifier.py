"""
lean_verifier.py

Writes a .lean file to lean_workspace/LeanEcon/, runs `lake build` from
lean_workspace/, and parses the result.

Responsibilities:
  - Write .lean source file into the Lean project source directory
  - Run `lake build` from the correct working directory (lean_workspace/)
  - Parse stdout/stderr: extract errors, warnings, success signal
  - Return a structured result dict

Critical path note:
  lake build must be run from lean_workspace/ (where lakefile.toml lives),
  NOT from lean_workspace/LeanEcon/ (that's the source module directory).
"""

import logging
import re
import subprocess
import textwrap
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
LEAN_WORKSPACE = PROJECT_ROOT / "lean_workspace"
LEAN_SOURCE_DIR = LEAN_WORKSPACE / "LeanEcon"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def _ensure_dirs():
    """Create outputs/ directory if it doesn't exist."""
    OUTPUTS_DIR.mkdir(exist_ok=True)


@contextmanager
def _preserve_proof_module() -> Path:
    """
    Preserve the tracked `LeanEcon/Proof.lean` contents across verification runs.

    The verifier still compiles by writing through `Proof.lean`, but we restore the
    original source afterward so smoke tests and stress runs do not leave the repo dirty.
    """
    lean_path = LEAN_SOURCE_DIR / "Proof.lean"
    original = lean_path.read_text(encoding="utf-8") if lean_path.exists() else None
    try:
        yield lean_path
    finally:
        if original is None:
            try:
                lean_path.unlink()
            except FileNotFoundError:
                pass
        else:
            lean_path.write_text(original, encoding="utf-8")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_lean_file(lean_code: str, filename: str | None = None) -> Path:
    """
    Write Lean 4 source code to lean_workspace/LeanEcon/Proof.lean.

    We always write to the fixed name `Proof.lean` because `LeanEcon.lean`
    imports `LeanEcon.Proof` — lake only compiles modules it knows about via
    import. The fixed name ensures lake detects the file change and recompiles.

    Args:
        lean_code: Complete .lean file content (must start with `import Mathlib`).
        filename: Ignored (kept for API compatibility). Always writes to Proof.lean.

    Returns:
        Path to lean_workspace/LeanEcon/Proof.lean.
    """
    _ensure_dirs()
    lean_path = LEAN_SOURCE_DIR / "Proof.lean"
    lean_path.write_text(lean_code, encoding="utf-8")
    return lean_path


def run_lake_build(lean_path: Path, timeout: int = 300) -> dict:
    """
    Run `lake build` from lean_workspace/ and capture the result.

    Args:
        lean_path: Path to the .lean file (used only for reporting; lake builds
                   the whole project).
        timeout: Maximum seconds to wait for lake build (default: 300 = 5 min).

    Returns:
        dict with keys:
          - success (bool): True if lake build exited with code 0.
          - returncode (int): Exit code from lake.
          - stdout (str): Captured standard output.
          - stderr (str): Captured standard error.
          - errors (list[str]): Parsed error lines from combined output.
          - warnings (list[str]): Parsed warning lines from combined output.
          - lean_file (str): Path to the .lean file that was verified.
    """
    try:
        result = subprocess.run(
            ["lake", "build"],
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
            "stderr": f"lake build timed out after {timeout}s",
            "errors": [f"Timeout after {timeout}s"],
            "warnings": [],
            "lean_file": str(lean_path),
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
        }

    combined = result.stdout + "\n" + result.stderr
    errors = _parse_diagnostics(combined, "error")
    warnings = _parse_diagnostics(combined, "warning")

    # `sorry` compiles with exit 0 in Lean 4 but emits a warning.
    # We treat any sorry usage as a failure.
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
    }


def verify(
    lean_code: str,
    filename: str | None = None,
    check_axioms: bool = True,
) -> dict:
    """
    Write .lean file and verify it with lake build in one call.

    This is the main entry point used by pipeline.py.

    Args:
        lean_code: Complete .lean file content.
        filename: Optional base name for the .lean file.
        check_axioms: If True and build succeeds, query lean_verify for axiom info.

    Returns:
        Build result dict (see run_lake_build) with added keys:
          - lean_code (str): The code that was verified.
          - axiom_info (dict | None): Axiom usage info, if available.
    """
    with _preserve_proof_module() as lean_path:
        lean_path = write_lean_file(lean_code, filename)
        result = run_lake_build(lean_path)
        result["lean_code"] = lean_code

        # Axiom check (only on success, best-effort, file must still exist)
        result["axiom_info"] = None
        if check_axioms and result["success"]:
            try:
                from lean_runner import verify_axioms, extract_theorem_name
                thm_name = extract_theorem_name(lean_code)
                if thm_name:
                    axiom_info = verify_axioms(str(lean_path), thm_name)
                    result["axiom_info"] = axiom_info
                    logger.info(
                        "Axiom check: %s — sound=%s",
                        axiom_info["axioms"], axiom_info["sound"],
                    )
            except Exception as exc:
                logger.warning("Axiom check failed: %s", exc)

        # Also save a copy to outputs/
        _save_to_outputs(lean_code, lean_path, result)

        return result


def _parse_diagnostics(text: str, level: str) -> list[str]:
    """
    Extract error or warning lines from lake build output.

    Lake formats diagnostics in one of two styles:
      A) Lean text format:  `LeanEcon/Proof.lean:5:2: error: message`
      B) Lake summary format: `error: LeanEcon/Proof.lean:5:2: message`

    We capture the message part and up to 3 continuation lines (for goal state).

    Args:
        text: Combined stdout + stderr from lake build.
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
            rest = line[len(level) + 2:]
            # Confirm it looks like a path diagnostic (contains .lean:N:M:)
            if re.match(r".*\.lean:\d+:\d+:", rest):
                loc_end = rest.index(":", rest.index(".lean:") + 6)
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
                if (next_line.startswith("  ") or next_line.startswith("| ")
                        or next_line.startswith("^") or next_line.startswith("⊢")):
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
    if result["stdout"].strip():
        report_lines.append("## lake stdout")
        report_lines.append("```")
        report_lines.append(result["stdout"].strip())
        report_lines.append("```")
    if result["stderr"].strip():
        report_lines.append("## lake stderr")
        report_lines.append("```")
        report_lines.append(result["stderr"].strip())
        report_lines.append("```")

    report_path = OUTPUTS_DIR / f"{stem}_report.md"
    result["output_lean"] = str(output_lean)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")


if __name__ == "__main__":
    print("Run tests via: python tests/test_verifier.py")
