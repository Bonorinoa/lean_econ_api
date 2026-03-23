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
from typing import Any

from dotenv import load_dotenv
from mistralai.client import Mistral

from formalization_search import FormalizationContext, build_formalization_context
from lean_verifier import run_direct_lean_check, write_lean_file
from leanstral_utils import call_leanstral, strip_fences
from preamble_library import find_matching_preambles
from prompts import (
    DIAGNOSE_SYSTEM_PROMPT,
    build_classify_prompt,
    build_formalize_prompt,
    build_repair_prompt,
)

# Load .env from project root (one level up from src/)
load_dotenv(Path(__file__).parent.parent / ".env")

FORMALIZE_TEMPERATURE = 0.3  # lower than proving (1.0) — we want conservative output
FORMALIZE_MAX_TOKENS = 4096  # theorem statements are short
MAX_FORMALIZATION_ATTEMPTS = 3
SORRY_VALIDATION_TIMEOUT = 120  # seconds for direct Lean fallback with sorry
_client: Mistral | None = None

REPAIR_BUCKET_UNKNOWN_IMPORT_MODULE = "unknown_import_module"
REPAIR_BUCKET_UNKNOWN_IDENTIFIER = "unknown_identifier"
REPAIR_BUCKET_TYPECLASS_INSTANCE = "typeclass_instance"
REPAIR_BUCKET_SYNTAX_NOTATION = "syntax_notation"
REPAIR_BUCKET_SEMANTIC_MISMATCH = "semantic_mismatch"

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
            for subsequent in lines[i + 1 :]:
                if subsequent.strip().startswith("-- Reason:"):
                    reason = subsequent.strip().removeprefix("-- Reason:").strip()
                    break
            return True, reason
    return False, None


def _inject_preamble_imports(lean_code: str, import_lines: list[str]) -> str:
    """Insert deduplicated preamble imports at the top of a Lean file."""
    if not import_lines:
        return lean_code

    lines = lean_code.splitlines()
    existing_imports = {line.strip() for line in lines if line.strip().startswith("import ")}
    new_imports = [line for line in import_lines if line not in existing_imports]
    if not new_imports:
        return lean_code

    insert_idx = 0
    while insert_idx < len(lines) and lines[insert_idx].strip().startswith("import "):
        insert_idx += 1

    prefix = lines[:insert_idx]
    suffix = lines[insert_idx:]
    updated = prefix + new_imports
    if suffix and suffix[0].strip():
        updated.append("")
    updated.extend(suffix)
    return "\n".join(updated).rstrip() + "\n"


def _normalize_imports(lean_code: str) -> str:
    """Drop obviously invalid bare imports and ensure `import Mathlib` is present."""
    lines = lean_code.splitlines()
    normalized: list[str] = []
    kept_imports: list[str] = []
    saw_import_block = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("import "):
            saw_import_block = True
            if (
                stripped == "import Mathlib"
                or stripped.startswith("import Mathlib.")
                or stripped.startswith("import LeanEcon.")
                or stripped.startswith("import Std")
            ):
                kept_imports.append(stripped)
            continue
        normalized.append(line)

    if "import Mathlib" not in kept_imports:
        kept_imports.insert(0, "import Mathlib")

    rebuilt: list[str] = []
    if kept_imports:
        rebuilt.extend(dict.fromkeys(kept_imports))
        rebuilt.append("")
    rebuilt.extend(normalized if saw_import_block else lines)
    return "\n".join(rebuilt).rstrip() + "\n"


def classify_repair_bucket(errors: list[str]) -> str:
    """Classify compiler failures into bounded repair buckets."""
    combined = " ".join(errors).lower()
    if any(
        token in combined
        for token in (
            "unknown module prefix",
            "unknown package",
            "unknown import",
            "did not find imported file",
        )
    ):
        return REPAIR_BUCKET_UNKNOWN_IMPORT_MODULE
    if any(
        token in combined
        for token in (
            "unknown identifier",
            "unknown constant",
            "unknown namespace",
            "invalid field notation",
        )
    ):
        return REPAIR_BUCKET_UNKNOWN_IDENTIFIER
    if any(
        token in combined
        for token in (
            "failed to synthesize",
            "typeclass",
            "instance problem",
            "has no instance",
        )
    ):
        return REPAIR_BUCKET_TYPECLASS_INSTANCE
    if any(
        token in combined
        for token in (
            "unexpected token",
            "invalid syntax",
            "parser error",
            "expected command",
            "expected term",
        )
    ):
        return REPAIR_BUCKET_SYNTAX_NOTATION
    return REPAIR_BUCKET_SEMANTIC_MISMATCH


def _apply_deterministic_repairs(
    lean_code: str,
    errors: list[str],
    context: FormalizationContext,
) -> tuple[str, list[str]]:
    """Apply bounded deterministic fixes before spending another model call."""
    repairs: list[str] = []
    repaired = lean_code
    bucket = classify_repair_bucket(errors)

    if bucket == REPAIR_BUCKET_UNKNOWN_IMPORT_MODULE:
        normalized_imports = _normalize_imports(repaired)
        if normalized_imports != repaired:
            repaired = normalized_imports
            repairs.append("normalize_imports")

    if context.preamble_imports:
        with_preambles = _inject_preamble_imports(repaired, context.preamble_imports)
        if with_preambles != repaired:
            repaired = with_preambles
            if "inject_preamble_imports" not in repairs:
                repairs.append("inject_preamble_imports")

    return repaired, repairs


def _build_formalizer_telemetry(
    context: FormalizationContext,
    *,
    model_calls: int,
    validation_methods: list[str],
    repair_buckets: list[str],
    deterministic_repairs_applied: list[str],
) -> dict[str, Any]:
    context_telemetry = context.telemetry()
    return {
        "model_calls": model_calls,
        "validation_method": validation_methods[-1] if validation_methods else None,
        "validation_methods": list(validation_methods),
        "repair_buckets": list(repair_buckets),
        "last_repair_bucket": repair_buckets[-1] if repair_buckets else None,
        "deterministic_repairs_applied": list(deterministic_repairs_applied),
        "selected_preambles": context_telemetry["selected_preambles"],
        "explicit_preambles": context_telemetry["explicit_preambles"],
        "auto_preambles": context_telemetry["auto_preambles"],
        "retrieval": context_telemetry["retrieval"],
        "mcp": context_telemetry["mcp"],
    }


def _diagnose_formalization_failure(
    claim_text: str,
    lean_code: str,
    errors: list[str],
) -> dict:
    """
    Analyze why formalization failed and produce actionable guidance.

    Returns dict with diagnosis, suggested_fix, fixable.
    """
    import json as _json

    client = _get_client()
    user_content = (
        f"Original claim:\n{claim_text}\n\n"
        f"Last Lean 4 code:\n{lean_code[:2000]}\n\n"
        f"Errors:\n" + "\n".join(errors[:5])
    )
    messages = [
        {"role": "system", "content": DIAGNOSE_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    try:
        raw = call_leanstral(
            client,
            messages,
            "diagnose",
            temperature=0.0,
            max_tokens=512,
        )
        result = _json.loads(raw.strip())
        return {
            "diagnosis": result.get("diagnosis", "Analysis unavailable."),
            "suggested_fix": result.get("suggested_fix"),
            "fixable": bool(result.get("fixable", False)),
        }
    except Exception as exc:
        print(f"[formalizer] Diagnosis failed: {exc}")
        return {
            "diagnosis": f"Formalization failed. Diagnosis error: {exc}",
            "suggested_fix": None,
            "fixable": False,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_claim(claim_text: str) -> dict:
    """
    Classify a claim into stable API-facing categories.

    The classifier prompt uses LLM-facing labels such as
    ALGEBRAIC_OR_CALCULUS and REQUIRES_CUSTOM_THEORY. This function maps those
    onto LeanEcon's API-facing categories and enriches them with preamble
    matching data.

    Returns:
        dict with keys:
          - category (str): "ALGEBRAIC", "DEFINABLE", "MATHLIB_NATIVE",
            or "REQUIRES_DEFINITIONS"
          - reason (str | None): Supporting detail from classifier output
          - definitions_needed (str | None): Detail from DEFINABLE classification
          - preamble_matches (list[str]): Names of matching preamble entries
          - suggested_reformulation (str | None): Guidance for the user
          - mathlib_hint (str | None): Mathlib navigation hint for MATHLIB_NATIVE
    """
    client = _get_client()
    messages = [
        {"role": "system", "content": build_classify_prompt()},
        {"role": "user", "content": claim_text},
    ]
    raw = call_leanstral(
        client,
        messages,
        "classify",
        temperature=0.0,
        max_tokens=512,
    )
    line = raw.strip().splitlines()[0].strip()

    def _result(
        *,
        category: str,
        reason: str | None = None,
        definitions_needed: str | None = None,
        preamble_matches: list[str] | None = None,
        suggested_reformulation: str | None = None,
        mathlib_hint: str | None = None,
    ) -> dict:
        return {
            "category": category,
            "reason": reason,
            "definitions_needed": definitions_needed,
            "preamble_matches": preamble_matches or [],
            "suggested_reformulation": suggested_reformulation,
            "mathlib_hint": mathlib_hint,
        }

    if line.startswith("REQUIRES_DEFINITIONS") or line.startswith("REQUIRES_CUSTOM_THEORY"):
        prefix = (
            "REQUIRES_DEFINITIONS"
            if line.startswith("REQUIRES_DEFINITIONS")
            else "REQUIRES_CUSTOM_THEORY"
        )
        reason = line.removeprefix(prefix).lstrip(":").strip() or None

        # Preamble rescue: check if we actually have definitions for this claim
        rescue_matches = find_matching_preambles(claim_text)
        if rescue_matches:
            match_names = [m.name for m in rescue_matches]
            match_descriptions = [m.description for m in rescue_matches]
            return _result(
                category="DEFINABLE",
                reason=reason,
                definitions_needed=reason,
                preamble_matches=match_names,
                suggested_reformulation=(
                    f"Initially classified as requiring unavailable definitions, "
                    f"but LeanEcon has built-in modules for: "
                    f"{', '.join(match_descriptions)}. "
                    f"Proceed to formalization."
                ),
            )

        return _result(category="REQUIRES_DEFINITIONS", reason=reason)

    if line.startswith("DEFINABLE"):
        detail = line.removeprefix("DEFINABLE").lstrip(":").strip() or None
        matches = find_matching_preambles(claim_text)
        match_names = [m.name for m in matches]

        if matches:
            match_descriptions = [m.description for m in matches]
            suggested = (
                f"This claim requires defining: {', '.join(match_descriptions)}. "
                f"LeanEcon has built-in definitions for these. "
                f"Proceed to formalization and the definitions will be "
                f"included automatically."
            )
        else:
            suggested = (
                f"This claim requires definitions not in LeanEcon's library: "
                f"{detail}. Try restating the claim as an algebraic identity "
                f"after substituting the functional forms."
            )

        return _result(
            category="DEFINABLE",
            reason=detail,
            definitions_needed=detail,
            preamble_matches=match_names,
            suggested_reformulation=suggested,
        )

    if line.startswith("MATHLIB_NATIVE"):
        detail = line.removeprefix("MATHLIB_NATIVE").lstrip(":").strip() or None
        rescue_matches = find_matching_preambles(claim_text)
        if rescue_matches:
            match_names = [m.name for m in rescue_matches]
            match_descriptions = [m.description for m in rescue_matches]
            return _result(
                category="DEFINABLE",
                reason=detail,
                definitions_needed=detail,
                preamble_matches=match_names,
                suggested_reformulation=(
                    f"The classifier pointed to Mathlib-native material ({detail}), "
                    f"but LeanEcon already has built-in modules for: "
                    f"{', '.join(match_descriptions)}. "
                    f"Proceed to formalization with the matching preamble entries."
                ),
            )
        return _result(
            category="MATHLIB_NATIVE",
            reason=detail,
            preamble_matches=[],
            suggested_reformulation=None,
            mathlib_hint=detail,
        )

    alg_matches = find_matching_preambles(claim_text)
    return _result(
        category="ALGEBRAIC",
        preamble_matches=[m.name for m in alg_matches],
    )


def sorry_validate(lean_code: str) -> dict:
    """
    Check that a Lean 4 file with sorry compiles (no errors except sorry warning).

    Tries lean_run_code first (fast, no file writes). Falls back to a direct
    `lake env lean` check on the legacy fixed file if lean_run_code is
    unavailable or fails.

    Returns:
        dict with keys:
          - valid (bool): True if only sorry warnings, no real errors.
          - errors (list[str]): Lean errors (empty if valid).
          - warnings (list[str]): Lean warnings (including sorry).
          - method (str): "lean_run_code" or "lake_env_lean".
    """
    # Fast path: lean_run_code via MCP (no file writes, ~2-5s)
    try:
        from lean_runner import run_code

        result = run_code(lean_code)
        return {
            "valid": result["valid"],
            "errors": result["errors"],
            "warnings": result["warnings"],
            "method": "lean_run_code",
        }
    except Exception:
        pass  # Fall through to direct Lean check

    # Slow path: write to Proof.lean + direct Lean check.
    lean_path = write_lean_file(lean_code)
    raw = run_direct_lean_check(lean_path, timeout=SORRY_VALIDATION_TIMEOUT)
    valid = raw["returncode"] == 0
    # Filter out the sorry pseudo-error injected by run_direct_lean_check.
    real_errors = [
        e
        for e in raw["errors"]
        if "declaration uses `sorry`" not in e and "Proof contains" not in e
    ]
    return {
        "valid": valid,
        "errors": real_errors if not valid else [],
        "warnings": raw["warnings"],
        "method": raw.get("verification_method", "lake_env_lean"),
    }


def formalize(
    claim_text: str,
    on_log: callable | None = None,
    preamble_names: list[str] | None = None,
) -> dict:
    """
    Translate a natural language / LaTeX claim into a Lean 4 theorem using Leanstral.

    Runs the formalize → sorry-validate → repair cycle up to
    MAX_FORMALIZATION_ATTEMPTS times. Optionally adds preamble imports.

    Args:
        claim_text: Cleaned claim text (output of parse_claim()["text"]).
        on_log: Optional logging callback (same pattern as pipeline.py).
        preamble_names: Optional list of preamble entry names to inject.

    Returns:
        dict with keys:
          - success (bool): True if sorry-validation passed.
          - theorem_code (str): Complete .lean file content (with sorry).
          - attempts (int): Number of formalize/repair cycles used.
          - errors (list[str]): Lean errors from the last failed attempt.
          - formalization_failed (bool): True if model said FORMALIZATION_FAILED.
          - failure_reason (str | None): Model's explanation if formalization_failed.
          - preamble_used (list[str]): Names of preamble modules injected.
          - diagnosis (str | None): Failure analysis (only on exhausted attempts).
          - suggested_fix (str | None): Concrete fix suggestion.
          - fixable (bool | None): Whether a human edit could fix it.
    """

    def _log(message: str, data: str | None = None, status: str = "done"):
        if on_log:
            on_log({"stage": "formalize", "message": message, "data": data, "status": status})
        else:
            print(f"[formalizer] {message}")

    _log("Starting formalization...", status="running")

    context = build_formalization_context(claim_text, explicit_preamble_names=preamble_names)
    preamble_used = list(context.preamble_names)
    if preamble_used:
        mode = "explicit" if context.explicit_preamble_names else "auto-selected"
        _log(f"Using {mode} preambles: {', '.join(preamble_used)}", status="running")

    # Formalize → sorry-validate → repair loop
    client = _get_client()
    lean_code = ""
    last_errors: list[str] = []
    validation_methods: list[str] = []
    repair_buckets: list[str] = []
    deterministic_repairs_applied: list[str] = []
    model_calls = 0
    system_prompt = build_formalize_prompt(
        preamble_block=context.preamble_block,
        context_block=context.build_prompt_block(),
    )

    for attempt in range(1, MAX_FORMALIZATION_ATTEMPTS + 1):
        if attempt == 1:
            _log(
                f"Attempt {attempt}/{MAX_FORMALIZATION_ATTEMPTS}: calling Leanstral...",
                status="running",
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": claim_text},
            ]
        else:
            repair_bucket = classify_repair_bucket(last_errors)
            repair_buckets.append(repair_bucket)
            _log(
                (
                    f"Attempt {attempt}/{MAX_FORMALIZATION_ATTEMPTS}: "
                    f"requesting {repair_bucket} repair..."
                ),
                status="running",
            )
            repair_content = (
                f"Original claim:\n{claim_text}\n\n"
                f"Failed Lean 4 file:\n{lean_code}\n\n"
                f"Errors:\n" + "\n".join(last_errors)
            )
            messages = [
                {
                    "role": "system",
                    "content": build_repair_prompt(
                        repair_bucket,
                        context_block=context.build_prompt_block(),
                    ),
                },
                {"role": "user", "content": repair_content},
            ]

        model_calls += 1
        raw = call_leanstral(
            client,
            messages,
            f"formalize_{attempt}",
            temperature=FORMALIZE_TEMPERATURE,
            max_tokens=FORMALIZE_MAX_TOKENS,
        )
        lean_code = strip_fences(raw)

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
                "preamble_used": preamble_used,
                "diagnosis": None,
                "suggested_fix": None,
                "fixable": None,
                "formalizer_telemetry": _build_formalizer_telemetry(
                    context,
                    model_calls=model_calls,
                    validation_methods=validation_methods,
                    repair_buckets=repair_buckets,
                    deterministic_repairs_applied=deterministic_repairs_applied,
                ),
            }

        if context.preamble_imports:
            lean_code = _inject_preamble_imports(lean_code, context.preamble_imports)

        _log(f"Attempt {attempt}: running sorry-validation...", data=lean_code, status="running")
        sv = sorry_validate(lean_code)
        validation_methods.append(sv.get("method", "unknown"))

        if sv["valid"]:
            _log(f"Sorry-validation passed on attempt {attempt}", status="done")
            return {
                "success": True,
                "theorem_code": lean_code,
                "attempts": attempt,
                "errors": [],
                "formalization_failed": False,
                "failure_reason": None,
                "preamble_used": preamble_used,
                "diagnosis": None,
                "suggested_fix": None,
                "fixable": None,
                "formalizer_telemetry": _build_formalizer_telemetry(
                    context,
                    model_calls=model_calls,
                    validation_methods=validation_methods,
                    repair_buckets=repair_buckets,
                    deterministic_repairs_applied=deterministic_repairs_applied,
                ),
            }

        last_errors = sv["errors"]
        _log(
            f"Attempt {attempt}: sorry-validation failed ({len(last_errors)} error(s))",
            data="\n".join(last_errors[:3]),
            status="error",
        )

        repaired_code, repairs = _apply_deterministic_repairs(lean_code, last_errors, context)
        if repairs:
            deterministic_repairs_applied.extend(
                repair for repair in repairs if repair not in deterministic_repairs_applied
            )
            lean_code = repaired_code
            _log(
                f"Attempt {attempt}: applying deterministic repair(s): {', '.join(repairs)}",
                status="running",
            )
            sv = sorry_validate(lean_code)
            validation_methods.append(sv.get("method", "unknown"))
            if sv["valid"]:
                _log(
                    f"Sorry-validation passed after deterministic repair on attempt {attempt}",
                    status="done",
                )
                return {
                    "success": True,
                    "theorem_code": lean_code,
                    "attempts": attempt,
                    "errors": [],
                    "formalization_failed": False,
                    "failure_reason": None,
                    "preamble_used": preamble_used,
                    "diagnosis": None,
                    "suggested_fix": None,
                    "fixable": None,
                    "formalizer_telemetry": _build_formalizer_telemetry(
                        context,
                        model_calls=model_calls,
                        validation_methods=validation_methods,
                        repair_buckets=repair_buckets,
                        deterministic_repairs_applied=deterministic_repairs_applied,
                    ),
                }
            last_errors = sv["errors"]

    # All attempts exhausted — run failure diagnosis
    _log("Running failure diagnosis...", status="running")
    try:
        diag = _diagnose_formalization_failure(claim_text, lean_code, last_errors)
    except Exception:
        diag = {"diagnosis": None, "suggested_fix": None, "fixable": None}
    _log(f"Diagnosis: {diag.get('diagnosis', 'unavailable')}", status="done")

    return {
        "success": False,
        "theorem_code": lean_code,
        "attempts": MAX_FORMALIZATION_ATTEMPTS,
        "errors": last_errors,
        "formalization_failed": False,
        "failure_reason": None,
        "preamble_used": preamble_used,
        "diagnosis": diag["diagnosis"],
        "suggested_fix": diag["suggested_fix"],
        "fixable": diag["fixable"],
        "formalizer_telemetry": _build_formalizer_telemetry(
            context,
            model_calls=model_calls,
            validation_methods=validation_methods,
            repair_buckets=repair_buckets,
            deterministic_repairs_applied=deterministic_repairs_applied,
        ),
    }


if __name__ == "__main__":
    print("Run tests via: pytest tests/test_formalizer.py")
