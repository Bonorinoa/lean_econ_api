"""Machine-readable error codes for every failure mode in the pipeline."""

from enum import Enum


class LeanEconErrorCode(str, Enum):
    """Machine-readable error codes for every failure mode in the pipeline."""

    # Classification
    CLASSIFICATION_REJECTED = "classification_rejected"
    CLASSIFICATION_FAILED = "classification_failed"

    # Formalization
    FORMALIZATION_FAILED = "formalization_failed"
    FORMALIZATION_TIMEOUT = "formalization_timeout"
    FORMALIZATION_UNFORMALIZABLE = "formalization_unformalizable"

    # Proving
    PROOF_NOT_FOUND = "proof_not_found"
    PROOF_TIMEOUT = "proof_timeout"

    # Verification
    VERIFICATION_REJECTED = "verification_rejected"
    VERIFICATION_SORRY = "verification_sorry"

    # System
    INTERNAL_ERROR = "internal_error"
    INVALID_INPUT = "invalid_input"

    # Success (not an error, but useful for uniform status handling)
    NONE = "none"
