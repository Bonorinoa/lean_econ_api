"""
formalizer.py

Translate natural language / LaTeX economics claims into valid Lean 4 theorem
statements using Leanstral. Validates each statement compiles with sorry before
sending it to the proving stage.

Uses the same Leanstral model (labs-leanstral-2603) as the proving stage, but
at lower temperature (0.3) for more conservative/deterministic output.

Public API:
  formalize(claim_text, on_log=None) -> dict   # main entry point
  sorry_validate(lean_code) -> dict             # sorry-tolerant compilation check
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from mistralai.client import Mistral

from lean_verifier import run_lake_build, write_lean_file
from leanstral_client import _strip_fences, call_leanstral
from prompts import (
    CLASSIFY_SYSTEM_PROMPT,
    FORMALIZE_SYSTEM_PROMPT,
    REPAIR_SYSTEM_PROMPT,
)

# Load .env from project root (one level up from src/)
load_dotenv(Path(__file__).parent.parent / ".env")

FORMALIZE_TEMPERATURE = 0.3   # lower than proving (1.0) — we want conservative output
FORMALIZE_MAX_TOKENS = 4096   # theorem statements are short
MAX_FORMALIZATION_ATTEMPTS = 3
SORRY_VALIDATION_TIMEOUT = 120  # seconds for lake build with sorry
_client: Mistral | None = None

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_client() -> Mistral:
    """Create the shared Mistral client lazily."""
    global _client
    if _client is None:
        _client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    return _client


def _detect_formalization_failed(lean_code: str) -> tuple[bool, str | None]:
    """Check if Leanstral signalled it cannot formalize this claim."""
    lines = lean_code.splitlines()[:5]
    for i, line in enumerate(lines):
        if "-- FORMALIZATION_FAILED" in line:
            reason = None
            for subsequent in lines[i + 1:]:
                if subsequent.strip().startswith("-- Reason:"):
                    reason = subsequent.strip().removeprefix("-- Reason:").strip()
                    break
            return True, reason
    return False, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_claim(claim_text: str) -> dict:
    """
    Pre-screen a claim to decide if formalization should be attempted.

    Uses a cheap single-line Leanstral call at temperature 0 to classify
    as ALGEBRAIC (formalizable) or REQUIRES_DEFINITIONS (not formalizable).

    Returns:
        dict with keys:
          - category (str): "ALGEBRAIC" or "REQUIRES_DEFINITIONS"
          - reason (str | None): Explanation if REQUIRES_DEFINITIONS
    """
    client = _get_client()
    messages = [
        {"role": "system", "content": CLASSIFY_SYSTEM_PROMPT},
        {"role": "user", "content": claim_text},
    ]
    raw = call_leanstral(
        client, messages, "classify",
        temperature=0.0,
        max_tokens=256,
    )
    line = raw.strip().splitlines()[0].strip()
    if line.startswith("REQUIRES_DEFINITIONS"):
        reason = line.removeprefix("REQUIRES_DEFINITIONS").lstrip(":").strip() or None
        return {"category": "REQUIRES_DEFINITIONS", "reason": reason}
    return {"category": "ALGEBRAIC", "reason": None}


def sorry_validate(lean_code: str) -> dict:
    """
    Check that a Lean 4 file with sorry compiles (no errors except sorry warning).

    Uses write_lean_file + run_lake_build directly and checks returncode == 0.
    Does NOT use lean_verifier.verify() which treats sorry as a failure.

    Returns:
        dict with keys:
          - valid (bool): True if only sorry warnings, no real errors.
          - errors (list[str]): Lean errors (empty if valid).
          - warnings (list[str]): Lean warnings (including sorry).
    """
    lean_path = write_lean_file(lean_code)
    raw = run_lake_build(lean_path, timeout=SORRY_VALIDATION_TIMEOUT)
    valid = raw["returncode"] == 0
    # Filter out the sorry pseudo-error injected by run_lake_build
    real_errors = [
        e for e in raw["errors"]
        if "declaration uses `sorry`" not in e and "Proof contains" not in e
    ]
    return {
        "valid": valid,
        "errors": real_errors if not valid else [],
        "warnings": raw["warnings"],
    }


def formalize(claim_text: str, on_log: callable | None = None) -> dict:
    """
    Translate a natural language / LaTeX claim into a Lean 4 theorem using Leanstral.

    Runs the formalize → sorry-validate → repair cycle up to
    MAX_FORMALIZATION_ATTEMPTS times.

    Args:
        claim_text: Cleaned claim text (output of parse_claim()["text"]).
        on_log: Optional logging callback (same pattern as pipeline.py).

    Returns:
        dict with keys:
          - success (bool): True if sorry-validation passed.
          - theorem_code (str): Complete .lean file content (with sorry).
          - attempts (int): Number of formalize/repair cycles used.
          - errors (list[str]): Lean errors from the last failed attempt.
          - formalization_failed (bool): True if model said FORMALIZATION_FAILED.
          - failure_reason (str | None): Model's explanation if formalization_failed.
    """
    def _log(message: str, data: str | None = None, status: str = "done"):
        if on_log:
            on_log({"stage": "formalize", "message": message, "data": data, "status": status})
        else:
            print(f"[formalizer] {message}")

    # Step 0: Pre-classify — avoid wasting formalization attempts on unformalizable claims
    _log("Pre-classifying claim...", status="running")
    classification = classify_claim(claim_text)
    if classification["category"] == "REQUIRES_DEFINITIONS":
        _log(f"Claim requires definitions not in Mathlib: {classification['reason']}", status="error")
        return {
            "success": False,
            "theorem_code": "",
            "attempts": 0,
            "errors": [],
            "formalization_failed": True,
            "failure_reason": classification["reason"],
        }
    _log("Claim classified as algebraic — proceeding", status="done")

    # Step 1+: Formalize → sorry-validate → repair loop
    client = _get_client()
    lean_code = ""
    last_errors: list[str] = []

    for attempt in range(1, MAX_FORMALIZATION_ATTEMPTS + 1):
        if attempt == 1:
            _log(f"Attempt {attempt}/{MAX_FORMALIZATION_ATTEMPTS}: calling Leanstral...", status="running")
            messages = [
                {"role": "system", "content": FORMALIZE_SYSTEM_PROMPT},
                {"role": "user", "content": claim_text},
            ]
        else:
            _log(f"Attempt {attempt}/{MAX_FORMALIZATION_ATTEMPTS}: requesting repair...", status="running")
            repair_content = (
                f"Original claim:\n{claim_text}\n\n"
                f"Failed Lean 4 file:\n{lean_code}\n\n"
                f"Errors:\n" + "\n".join(last_errors)
            )
            messages = [
                {"role": "system", "content": REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": repair_content},
            ]

        raw = call_leanstral(
            client, messages, f"formalize_{attempt}",
            temperature=FORMALIZE_TEMPERATURE,
            max_tokens=FORMALIZE_MAX_TOKENS,
        )
        lean_code = _strip_fences(raw)

        failed, reason = _detect_formalization_failed(lean_code)
        if failed:
            _log(f"Leanstral flagged claim as unformalizable: {reason}", status="error")
            return {
                "success": False,
                "theorem_code": lean_code,
                "attempts": attempt,
                "errors": [],
                "formalization_failed": True,
                "failure_reason": reason,
            }

        _log(f"Attempt {attempt}: running sorry-validation...", data=lean_code, status="running")
        sv = sorry_validate(lean_code)

        if sv["valid"]:
            _log(f"Sorry-validation passed on attempt {attempt}", status="done")
            return {
                "success": True,
                "theorem_code": lean_code,
                "attempts": attempt,
                "errors": [],
                "formalization_failed": False,
                "failure_reason": None,
            }

        last_errors = sv["errors"]
        _log(
            f"Attempt {attempt}: sorry-validation failed ({len(last_errors)} error(s))",
            data="\n".join(last_errors[:3]),
            status="error",
        )

    return {
        "success": False,
        "theorem_code": lean_code,
        "attempts": MAX_FORMALIZATION_ATTEMPTS,
        "errors": last_errors,
        "formalization_failed": False,
        "failure_reason": None,
    }


if __name__ == "__main__":
    print("Run tests via: python tests/test_formalizer.py")
