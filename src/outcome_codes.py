"""Shared error-code classification helpers for LeanEcon outcomes."""

from __future__ import annotations

from typing import Any, Mapping

from error_codes import LeanEconErrorCode


def formalize_error_code(result: Mapping[str, Any]) -> LeanEconErrorCode:
    """Map a formalization result to a stable machine-readable error code."""
    if result.get("success"):
        return LeanEconErrorCode.NONE

    failure_reason = str(result.get("failure_reason") or "").lower()
    diagnosis = str(result.get("diagnosis") or "").lower()
    errors = " ".join(str(item) for item in result.get("errors", [])).lower()
    combined = " ".join(part for part in (failure_reason, diagnosis, errors) if part)

    if "timeout" in combined:
        return LeanEconErrorCode.FORMALIZATION_TIMEOUT
    if result.get("formalization_failed"):
        if any(
            keyword in failure_reason
            for keyword in ("unformalizable", "not supported", "requires", "definition")
        ):
            return LeanEconErrorCode.FORMALIZATION_UNFORMALIZABLE
        return LeanEconErrorCode.FORMALIZATION_FAILED
    return LeanEconErrorCode.FORMALIZATION_FAILED


def verify_error_code(result: Mapping[str, Any]) -> LeanEconErrorCode:
    """Map a verification result to a stable machine-readable error code."""
    if result.get("success"):
        return LeanEconErrorCode.NONE
    if result.get("stop_reason") == "timeout":
        return LeanEconErrorCode.PROOF_TIMEOUT
    lean_code = str(result.get("lean_code") or "")
    if lean_code and "sorry" in lean_code:
        return LeanEconErrorCode.VERIFICATION_SORRY
    if result.get("proof_generated") is False:
        return LeanEconErrorCode.PROOF_NOT_FOUND
    return LeanEconErrorCode.VERIFICATION_REJECTED
