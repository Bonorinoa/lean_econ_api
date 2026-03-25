"""
formalizer.py

Translate natural language / LaTeX economics claims into valid Lean 4 theorem
statements using the configured Leanstral-compatible model. Each candidate is
validated with `sorry` before it reaches the proving stage.

The formalizer now runs on a bounded budget: up to two model calls and three
validations, with deterministic repairs attempted before a second repair prompt.

Public API:
  formalize(claim_text, on_log=None) -> dict   # main entry point
  sorry_validate(lean_code) -> dict             # sorry-tolerant compilation check
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from formalization_search import FormalizationContext, build_formalization_context
from lean_diagnostics import extract_json_object
from lean_verifier import run_direct_lean_check, write_lean_file
from leanstral_utils import call_leanstral, get_client, strip_fences
from mcp_runtime import formalization_mcp_available
from model_config import LEANSTRAL_MODEL, model_fingerprint
from preamble_library import find_matching_preambles
from prompts import (
    DIAGNOSE_SYSTEM_PROMPT,
    build_classify_prompt,
    build_formalize_prompt,
    build_repair_prompt,
)
from provider_telemetry import summarize_provider_calls
from result_cache import formalization_cache

# Load .env from project root (one level up from src/)
load_dotenv(Path(__file__).parent.parent / ".env")

FORMALIZE_TEMPERATURE = 0.3  # lower than proving (1.0) — we want conservative output
FORMALIZE_MAX_TOKENS = 4096  # theorem statements are short
MAX_FORMALIZATION_MODEL_CALLS = 2
MAX_FORMALIZATION_VALIDATIONS = 3
SORRY_VALIDATION_TIMEOUT = 120  # seconds for direct Lean fallback with sorry
FORMALIZATION_CACHE_NAMESPACE = model_fingerprint(
    scope="formalize",
    extras={
        "temperature": FORMALIZE_TEMPERATURE,
        "max_tokens": FORMALIZE_MAX_TOKENS,
        "model_calls": MAX_FORMALIZATION_MODEL_CALLS,
        "validations": MAX_FORMALIZATION_VALIDATIONS,
    },
)

REPAIR_BUCKET_UNKNOWN_IMPORT_MODULE = "unknown_import_module"
REPAIR_BUCKET_UNKNOWN_IDENTIFIER = "unknown_identifier"
REPAIR_BUCKET_TYPECLASS_INSTANCE = "typeclass_instance"
REPAIR_BUCKET_SYNTAX_NOTATION = "syntax_notation"
REPAIR_BUCKET_SEMANTIC_MISMATCH = "semantic_mismatch"
DECLARATION_SUFFIX_BYTES = 6
LEAN_RUN_CODE_NO_PROJECT_PATH = "lean_run_code_unavailable:no_project_path"
LEAN_RUN_CODE_COOLDOWN = "lean_run_code_unavailable:cooldown"
LEAN_RUN_CODE_GENERIC_UNAVAILABLE = "lean_run_code_unavailable"
WRAPPER_TEXT_ERROR = "formalizer output contained explanation text or markdown fences"
MISPLACED_IMPORT_ERROR = "formalizer output placed `import` after non-import Lean code"
BICONDITIONAL_REWRITE_ERROR = (
    "formalizer output changed a one-way claim into a biconditional; "
    "replace `↔` with hypotheses implying the conclusion"
)
TAUTOLOGY_ERROR = "formalizer output collapsed the claim into a tautology"
SPECIALIZATION_ERROR = (
    "formalizer output narrowed the claim to an unrelated special functional form"
)
CONTRACTING_SCALAR_ERROR = (
    "formalizer output gave ContractingWith a real-valued coefficient instead of NNReal"
)
UNIQUE_DECLARATION_MARKER = "_leanecon_"
_LEAN_RUN_CODE_DISABLED_REASON: str | None = None

DECLARATION_RE = re.compile(r"(?m)^\s*(theorem|lemma)\s+([A-Za-z_][A-Za-z0-9_']*)\b")
LEAN_COMMAND_PREFIXES = (
    "import ",
    "open ",
    "theorem ",
    "lemma ",
    "example ",
    "def ",
    "noncomputable ",
    "namespace ",
    "section ",
    "variable ",
    "/-",
    "--",
    "#",
)
SPECIALIZED_FORM_IMPORT_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "LeanEcon.Preamble.Producer.CobbDouglas2Factor",
        ("cobb-douglas", "cobb douglas", "output elasticity", "factor share"),
    ),
    (
        "LeanEcon.Preamble.Producer.CES2Factor",
        ("ces", "constant elasticity of substitution", "elasticity of substitution"),
    ),
    (
        "LeanEcon.Preamble.Consumer.CRRAUtility",
        ("crra", "isoelastic", "power utility", "constant relative risk aversion"),
    ),
    (
        "LeanEcon.Preamble.Consumer.CARAUtility",
        ("cara", "constant absolute risk aversion", "exponential utility"),
    ),
    (
        "LeanEcon.Preamble.Consumer.StoneGearyUtility",
        ("stone-geary", "stone geary", "les utility"),
    ),
)

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


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


def _normalized_validation_fallback_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    lowered = reason.lower()
    if "no valid lean project path found" in lowered:
        return LEAN_RUN_CODE_NO_PROJECT_PATH
    if "temporarily disabled after recent failure" in lowered:
        return LEAN_RUN_CODE_COOLDOWN
    if "timed out" in lowered:
        return "lean_run_code_unavailable:timeout"
    if "mcp error" in lowered:
        return "lean_run_code_unavailable:mcp_error"
    return LEAN_RUN_CODE_GENERIC_UNAVAILABLE


def _is_comment_line(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith(("--", "/-", "-/"))


def _first_meaningful_command_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _is_comment_line(line):
            continue
        if stripped.startswith(LEAN_COMMAND_PREFIXES):
            return index
        return None
    return None


def _uniquify_primary_declaration_name(claim_text: str, lean_code: str) -> str:
    """Append a deterministic suffix to theorem/lemma names to avoid collisions."""
    match = DECLARATION_RE.search(lean_code)
    if match is None:
        return lean_code

    original_name = match.group(2)
    if UNIQUE_DECLARATION_MARKER in original_name:
        return lean_code

    suffix = hashlib.sha256(claim_text.strip().encode("utf-8")).hexdigest()[
        :DECLARATION_SUFFIX_BYTES
    ]
    unique_name = f"{original_name}{UNIQUE_DECLARATION_MARKER}{suffix}"
    start, end = match.span(2)
    return lean_code[:start] + unique_name + lean_code[end:]


def _has_wrapper_text(raw_output: str) -> bool:
    stripped = raw_output.strip()
    lines = [line for line in stripped.splitlines() if not line.strip().startswith("```")]
    command_index = _first_meaningful_command_index(lines)
    if command_index is None:
        return bool(strip_fences(raw_output))

    for line in lines[:command_index]:
        if not _is_comment_line(line):
            return True
    return False


def _header_before_proof(lean_code: str) -> str:
    proof_index = lean_code.find(":= by")
    if proof_index == -1:
        return lean_code
    return lean_code[:proof_index]


def _proposition_text(lean_code: str) -> str:
    header = _header_before_proof(lean_code)
    if ":" not in header:
        return ""
    return header.rsplit(":", 1)[1].strip()


def _normalized_prop(prop: str) -> str:
    return " ".join(prop.split())


def _conclusion_text(prop: str) -> str:
    normalized = _normalized_prop(prop)
    if not normalized:
        return ""
    parts = re.split(r"\s*→\s*", normalized)
    return parts[-1].strip() if parts else normalized


def _claim_mentions(claim_text: str, *phrases: str) -> bool:
    lowered = claim_text.lower()
    return any(phrase in lowered for phrase in phrases)


def _is_reflexive_statement(prop: str) -> bool:
    normalized = _normalized_prop(prop)
    for token in (" ↔ ", " = "):
        if token not in normalized:
            continue
        left, right = normalized.rsplit(token, 1)
        left_clean = re.sub(r"^\(+|\)+$", "", left.strip())
        right_clean = re.sub(r"^\(+|\)+$", "", right.strip())
        if left_clean and left_clean == right_clean:
            return True
    return False


def _has_misplaced_import(lean_code: str) -> bool:
    saw_non_import_code = False
    for line in lean_code.splitlines():
        stripped = line.strip()
        if not stripped or _is_comment_line(line):
            continue
        if stripped.startswith("import "):
            if saw_non_import_code:
                return True
            continue
        if stripped.startswith("open "):
            saw_non_import_code = True
            continue
        if stripped.startswith(LEAN_COMMAND_PREFIXES):
            saw_non_import_code = True
    return False


def _has_unrelated_specialization(claim_text: str, lean_code: str) -> bool:
    lowered_claim = claim_text.lower()
    imports = {
        line.strip() for line in lean_code.splitlines() if line.strip().startswith("import ")
    }
    for import_line, hints in SPECIALIZED_FORM_IMPORT_HINTS:
        if f"import {import_line}" not in imports:
            continue
        if any(hint in lowered_claim for hint in hints):
            continue
        return True
    return False


def _has_contractingwith_scalar_mismatch(lean_code: str) -> bool:
    if "ContractingWith" not in lean_code:
        return False

    header = _header_before_proof(lean_code)
    real_scalars: set[str] = set()
    for binder_names, binder_type in re.findall(r"\(([^:()]+):\s*([^)]+)\)", header):
        normalized_type = " ".join(binder_type.split())
        if normalized_type not in {"ℝ", "Real"}:
            continue
        for candidate in binder_names.split():
            cleaned = candidate.strip("{}[]")
            if cleaned:
                real_scalars.add(cleaned)

    return any(f"ContractingWith {name}" in header for name in real_scalars)


def _has_extreme_value_shape(claim_text: str, prop: str) -> bool:
    conclusion = _conclusion_text(prop)
    if not conclusion:
        return False
    lowered_claim = claim_text.lower()
    mentions_maximum = _claim_mentions(
        lowered_claim,
        "attains a maximum",
        "attains maximum",
        "attains its maximum",
    )
    mentions_minimum = _claim_mentions(
        lowered_claim,
        "attains a minimum",
        "attains minimum",
        "attains its minimum",
    )
    if mentions_maximum and ("∃" not in conclusion or "IsMaxOn" not in conclusion):
        return False
    if mentions_minimum and ("∃" not in conclusion or "IsMinOn" not in conclusion):
        return False
    return mentions_maximum or mentions_minimum


def _has_convergence_shape(prop: str) -> bool:
    conclusion = _conclusion_text(prop)
    return "Tendsto" in conclusion or "Convergent" in conclusion


def _candidate_acceptance_errors(
    claim_text: str,
    lean_code: str,
) -> list[str]:
    errors: list[str] = []
    if "```" in lean_code:
        errors.append(WRAPPER_TEXT_ERROR)
    if _has_misplaced_import(lean_code):
        errors.append(MISPLACED_IMPORT_ERROR)

    prop = _proposition_text(lean_code)
    lowered_claim = claim_text.lower()
    if (
        prop
        and "↔" in prop
        and not _claim_mentions(
            lowered_claim,
            "if and only if",
            "iff",
            "equivalent",
            "equivalence",
        )
    ):
        errors.append(BICONDITIONAL_REWRITE_ERROR)
    if prop and _is_reflexive_statement(prop):
        errors.append(TAUTOLOGY_ERROR)
    if _has_extreme_value_shape(claim_text, prop) is False and _claim_mentions(
        lowered_claim,
        "attains a maximum",
        "attains maximum",
        "attains its maximum",
        "attains a minimum",
        "attains minimum",
        "attains its minimum",
    ):
        errors.append("formalizer output dropped existence-shaped extreme-value conclusion")
    if (
        _claim_mentions(lowered_claim, "has a fixed point", "there exists a fixed point")
        and "∃" not in prop
    ):
        errors.append("formalizer output dropped existence from a fixed-point claim")
    if _claim_mentions(lowered_claim, "unique fixed point") and "∃!" not in prop:
        errors.append("formalizer output dropped uniqueness from a fixed-point claim")
    if _claim_mentions(lowered_claim, "converges", "convergent", "convergence") and not (
        prop and _has_convergence_shape(prop)
    ):
        errors.append("formalizer output dropped convergence-shaped conclusion")
    if _has_unrelated_specialization(claim_text, lean_code):
        errors.append(SPECIALIZATION_ERROR)
    if _has_contractingwith_scalar_mismatch(lean_code):
        errors.append(CONTRACTING_SCALAR_ERROR)
    return errors


def _prepare_candidate_for_validation(
    *,
    claim_text: str,
    raw_output: str,
    context: FormalizationContext,
) -> tuple[str, list[str], list[str]]:
    structural_repairs: list[str] = []
    if _has_wrapper_text(raw_output):
        structural_repairs.append("strip_wrapper_text")

    lean_code = strip_fences(raw_output)
    if context.preamble_imports:
        lean_code = _inject_preamble_imports(lean_code, context.preamble_imports)
    uniquified = _uniquify_primary_declaration_name(claim_text, lean_code)
    if uniquified != lean_code:
        lean_code = uniquified
        structural_repairs.append("uniquify_declaration_name")
    if _has_misplaced_import(lean_code):
        normalized = _normalize_imports(lean_code)
        if normalized != lean_code:
            lean_code = normalized
            structural_repairs.append("normalize_imports")
    return lean_code, structural_repairs, _candidate_acceptance_errors(claim_text, lean_code)


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
    validation_fallback_reasons: list[str],
    repair_buckets: list[str],
    deterministic_repairs_applied: list[str],
    cache_hit: bool,
    provider_calls: list[dict[str, Any]],
) -> dict[str, Any]:
    context_telemetry = context.telemetry()
    provider_telemetry = summarize_provider_calls(provider_calls)
    return {
        "model": LEANSTRAL_MODEL,
        "cache_hit": cache_hit,
        "cache_namespace": FORMALIZATION_CACHE_NAMESPACE,
        "model_calls": model_calls,
        "validation_method": validation_methods[-1] if validation_methods else None,
        "validation_methods": list(validation_methods),
        "validation_fallback_reasons": list(validation_fallback_reasons),
        "repair_buckets": list(repair_buckets),
        "last_repair_bucket": repair_buckets[-1] if repair_buckets else None,
        "deterministic_repairs_applied": list(deterministic_repairs_applied),
        "selected_preambles": context_telemetry["selected_preambles"],
        "explicit_preambles": context_telemetry["explicit_preambles"],
        "auto_preambles": context_telemetry["auto_preambles"],
        "retrieval": context_telemetry["retrieval"],
        "mcp": context_telemetry["mcp"],
        "provider_telemetry": provider_telemetry,
    }


def _formalization_cache_key(
    claim_text: str,
    context: FormalizationContext,
) -> dict[str, Any]:
    return {
        "claim_text": claim_text.strip(),
        "preamble_names": list(context.preamble_names),
        "namespace": FORMALIZATION_CACHE_NAMESPACE,
    }


def _build_formalize_result(
    *,
    success: bool,
    theorem_code: str,
    attempts: int,
    errors: list[str],
    formalization_failed: bool,
    failure_reason: str | None,
    preamble_used: list[str],
    diagnosis: str | None,
    suggested_fix: str | None,
    fixable: bool | None,
    formalizer_telemetry: dict[str, Any],
) -> dict[str, Any]:
    return {
        "success": success,
        "theorem_code": theorem_code,
        "attempts": attempts,
        "errors": errors,
        "formalization_failed": formalization_failed,
        "failure_reason": failure_reason,
        "preamble_used": preamble_used,
        "diagnosis": diagnosis,
        "suggested_fix": suggested_fix,
        "fixable": fixable,
        "formalizer_telemetry": formalizer_telemetry,
    }


def _diagnose_formalization_failure(
    claim_text: str,
    lean_code: str,
    errors: list[str],
    provider_calls: list[dict[str, Any]] | None = None,
) -> dict:
    """
    Analyze why formalization failed and produce actionable guidance.

    Returns dict with diagnosis, suggested_fix, fixable.
    """
    client = get_client()
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
            telemetry_out=provider_calls,
        )
        result = extract_json_object(raw)
        if result is None:
            raise ValueError("diagnoser did not return a JSON object")
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


def classify_claim(
    claim_text: str,
    telemetry_out: list[dict[str, Any]] | None = None,
) -> dict:
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
    client = get_client()
    provider_telemetry = (
        summarize_provider_calls(telemetry_out) if telemetry_out is not None else None
    )
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
            "provider_telemetry": provider_telemetry,
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
    global _LEAN_RUN_CODE_DISABLED_REASON

    fallback_reason = None
    allowed, availability_reason = formalization_mcp_available()
    if _LEAN_RUN_CODE_DISABLED_REASON and availability_reason is None:
        allowed = False
        availability_reason = _LEAN_RUN_CODE_DISABLED_REASON

    if allowed:
        try:
            from lean_runner import run_code

            result = run_code(lean_code)
            _LEAN_RUN_CODE_DISABLED_REASON = None
            return {
                "valid": result["valid"],
                "errors": result["errors"],
                "warnings": result["warnings"],
                "method": "lean_run_code",
            }
        except Exception as exc:
            fallback_reason = _normalized_validation_fallback_reason(str(exc))
            if fallback_reason and fallback_reason != LEAN_RUN_CODE_COOLDOWN:
                _LEAN_RUN_CODE_DISABLED_REASON = fallback_reason
    else:
        fallback_reason = _normalized_validation_fallback_reason(availability_reason)

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
    result = {
        "valid": valid,
        "errors": real_errors if not valid else [],
        "warnings": raw["warnings"],
        "method": raw.get("verification_method", "lake_env_lean"),
    }
    if fallback_reason:
        result["fallback_reason"] = fallback_reason
    return result


def formalize(
    claim_text: str,
    on_log: callable | None = None,
    preamble_names: list[str] | None = None,
    use_cache: bool = True,
) -> dict:
    """
    Translate a natural language / LaTeX claim into a Lean 4 theorem using Leanstral.

    Runs a bounded formalize → sorry-validate → repair cycle with at most two
    model calls and three validations. Optionally adds preamble imports.

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

    def _telemetry(*, cache_hit: bool) -> dict[str, Any]:
        return _build_formalizer_telemetry(
            context,
            model_calls=model_calls,
            validation_methods=validation_methods,
            validation_fallback_reasons=validation_fallback_reasons,
            repair_buckets=repair_buckets,
            deterministic_repairs_applied=deterministic_repairs_applied,
            cache_hit=cache_hit,
            provider_calls=provider_calls,
        )

    def _result(
        *,
        success: bool,
        theorem_code: str,
        attempts: int,
        errors: list[str],
        formalization_failed: bool,
        failure_reason: str | None,
        diagnosis: str | None,
        suggested_fix: str | None,
        fixable: bool | None,
        cache_hit: bool = False,
    ) -> dict[str, Any]:
        return _build_formalize_result(
            success=success,
            theorem_code=theorem_code,
            attempts=attempts,
            errors=errors,
            formalization_failed=formalization_failed,
            failure_reason=failure_reason,
            preamble_used=preamble_used,
            diagnosis=diagnosis,
            suggested_fix=suggested_fix,
            fixable=fixable,
            formalizer_telemetry=_telemetry(cache_hit=cache_hit),
        )

    def _record_validation(lean_code: str) -> dict[str, Any]:
        nonlocal validation_calls
        validation_calls += 1
        validation = sorry_validate(lean_code)
        validation_methods.append(validation.get("method", "unknown"))
        fallback_reason = _normalized_validation_fallback_reason(validation.get("fallback_reason"))
        if fallback_reason:
            normalized = str(fallback_reason)
            if not validation_fallback_reasons or validation_fallback_reasons[-1] != normalized:
                validation_fallback_reasons.append(normalized)
        return validation

    _log("Starting formalization...", status="running")

    context = build_formalization_context(claim_text, explicit_preamble_names=preamble_names)
    preamble_used = list(context.preamble_names)
    if preamble_used:
        mode = "explicit" if context.explicit_preamble_names else "auto-selected"
        _log(f"Using {mode} preambles: {', '.join(preamble_used)}", status="running")

    cache_key = _formalization_cache_key(claim_text, context)
    if use_cache:
        cached = formalization_cache.get(cache_key)
        if cached is not None:
            _log("Formalization cache hit", status="done")
            cached_result = dict(cached)
            cached_telemetry = dict(cached.get("formalizer_telemetry", {}))
            if "provider_telemetry" in cached_telemetry:
                cached_telemetry["cached_provider_telemetry"] = cached_telemetry[
                    "provider_telemetry"
                ]
            cached_telemetry["provider_telemetry"] = summarize_provider_calls([])
            cached_result["formalizer_telemetry"] = {
                **cached_telemetry,
                "cache_hit": True,
            }
            return cached_result

    client = get_client()
    lean_code = ""
    last_errors: list[str] = []
    validation_methods: list[str] = []
    validation_fallback_reasons: list[str] = []
    repair_buckets: list[str] = []
    deterministic_repairs_applied: list[str] = []
    provider_calls: list[dict[str, Any]] = []
    model_calls = 0
    validation_calls = 0
    system_prompt = build_formalize_prompt(
        preamble_block=context.preamble_block,
        context_block=context.build_prompt_block(),
    )

    for attempt in range(1, MAX_FORMALIZATION_MODEL_CALLS + 1):
        if attempt == 1:
            _log(
                f"Attempt {attempt}/{MAX_FORMALIZATION_MODEL_CALLS}: calling Leanstral...",
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
                    f"Attempt {attempt}/{MAX_FORMALIZATION_MODEL_CALLS}: "
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
            telemetry_out=provider_calls,
        )
        lean_code = strip_fences(raw)

        failed, reason = _detect_formalization_failed(lean_code)
        if failed:
            _log(f"Leanstral flagged claim as unformalizable: {reason}", status="error")
            result = _result(
                success=False,
                theorem_code=lean_code,
                attempts=attempt,
                errors=[],
                formalization_failed=True,
                failure_reason=reason,
                diagnosis=None,
                suggested_fix=None,
                fixable=None,
            )
            if use_cache:
                formalization_cache.put(cache_key, result)
            return result

        lean_code, structural_repairs, acceptance_errors = _prepare_candidate_for_validation(
            claim_text=claim_text,
            raw_output=raw,
            context=context,
        )
        new_repairs = [
            repair for repair in structural_repairs if repair not in deterministic_repairs_applied
        ]
        if new_repairs:
            deterministic_repairs_applied.extend(new_repairs)
            _log(
                f"Attempt {attempt}: applied structural cleanup: {', '.join(new_repairs)}",
                status="running",
            )

        if acceptance_errors:
            last_errors = acceptance_errors
            _log(
                f"Attempt {attempt}: candidate rejected before validation",
                data="\n".join(last_errors[:3]),
                status="error",
            )
            continue

        _log(f"Attempt {attempt}: running sorry-validation...", data=lean_code, status="running")
        sv = _record_validation(lean_code)

        if sv["valid"]:
            _log(f"Sorry-validation passed on attempt {attempt}", status="done")
            result = _result(
                success=True,
                theorem_code=lean_code,
                attempts=attempt,
                errors=[],
                formalization_failed=False,
                failure_reason=None,
                diagnosis=None,
                suggested_fix=None,
                fixable=None,
            )
            if use_cache:
                formalization_cache.put(cache_key, result)
            return result

        last_errors = sv["errors"]
        _log(
            f"Attempt {attempt}: sorry-validation failed ({len(last_errors)} error(s))",
            data="\n".join(last_errors[:3]),
            status="error",
        )

        if attempt == 1 and validation_calls < MAX_FORMALIZATION_VALIDATIONS:
            repaired_code, repairs = _apply_deterministic_repairs(lean_code, last_errors, context)
        else:
            repaired_code, repairs = lean_code, []
        if repairs and validation_calls < MAX_FORMALIZATION_VALIDATIONS:
            deterministic_repairs_applied.extend(
                repair for repair in repairs if repair not in deterministic_repairs_applied
            )
            lean_code = repaired_code
            _log(
                f"Attempt {attempt}: applying deterministic repair(s): {', '.join(repairs)}",
                status="running",
            )
            sv = _record_validation(lean_code)
            if sv["valid"]:
                _log(
                    f"Sorry-validation passed after deterministic repair on attempt {attempt}",
                    status="done",
                )
                result = _result(
                    success=True,
                    theorem_code=lean_code,
                    attempts=attempt,
                    errors=[],
                    formalization_failed=False,
                    failure_reason=None,
                    diagnosis=None,
                    suggested_fix=None,
                    fixable=None,
                )
                if use_cache:
                    formalization_cache.put(cache_key, result)
                return result
            last_errors = sv["errors"]
        elif repairs:
            _log(
                "Validation budget exhausted before checking deterministic repairs",
                status="error",
            )

    # All attempts exhausted — run failure diagnosis
    _log("Running failure diagnosis...", status="running")
    try:
        diag = _diagnose_formalization_failure(
            claim_text,
            lean_code,
            last_errors,
            provider_calls=provider_calls,
        )
    except Exception:
        diag = {"diagnosis": None, "suggested_fix": None, "fixable": None}
    _log(f"Diagnosis: {diag.get('diagnosis', 'unavailable')}", status="done")

    return _result(
        success=False,
        theorem_code=lean_code,
        attempts=model_calls,
        errors=last_errors,
        formalization_failed=False,
        failure_reason=None,
        diagnosis=diag["diagnosis"],
        suggested_fix=diag["suggested_fix"],
        fixable=diag["fixable"],
    )


if __name__ == "__main__":
    print("Run tests via: pytest tests/test_formalizer.py")
