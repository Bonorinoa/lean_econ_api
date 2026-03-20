"""Heuristic claim-difficulty estimates for the Verify page."""

from __future__ import annotations

import re


def estimate_difficulty(claim_text: str) -> dict:
    """Estimate proving difficulty from lightweight keyword heuristics."""
    normalized = claim_text.strip().lower()

    unsupported_patterns = (
        r"\bequilibrium\b",
        r"\bwelfare theorem\b",
        r"\bfixed point\b",
        r"\bnash\b",
    )
    medium_patterns = (
        r"\brpow\b",
        r"\bvariable exponent",
        r"\bvariable exponents\b",
        r"\bderivative\b",
        r"\bdifferentiat",
        r"\bd/d",
    )
    easy_patterns = (
        r"\belasticity\b",
        r"\bbudget\b",
        r"\bconstant\b",
        r"\bidentity\b",
        r"\bequal(?:ity)?\b",
        r"\bequals\b",
        r"\bis equal to\b",
        r"\beven\b",
        r"\bodd\b",
        r"\bsum\b",
        r"\bproduct\b",
    )

    if any(re.search(pattern, normalized) for pattern in unsupported_patterns):
        return {
            "level": "unsupported",
            "confidence": 0.95,
            "reason": (
                "Claims about equilibrium, welfare theorems, fixed points, or Nash "
                "concepts usually need definitions LeanEcon does not yet encode."
            ),
        }

    if any(re.search(pattern, normalized) for pattern in medium_patterns):
        return {
            "level": "medium",
            "confidence": 0.8,
            "reason": (
                "Claims with `rpow`, variable exponents, or derivatives often need "
                "extra guidance and may take multiple attempts."
            ),
        }

    if any(re.search(pattern, normalized) for pattern in easy_patterns) or "=" in normalized:
        return {
            "level": "easy",
            "confidence": 0.8,
            "reason": "Algebraic claims like this typically verify on the first attempt.",
        }

    return {
        "level": "hard",
        "confidence": 0.6,
        "reason": (
            "This claim does not match the current easy heuristics and may need "
            "manual review or several proving attempts."
        ),
    }
