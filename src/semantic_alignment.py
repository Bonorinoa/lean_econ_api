"""Semantic-alignment grading helpers for evaluation scripts."""

from __future__ import annotations

import json
from typing import Any

from leanstral_utils import call_leanstral, get_client
from provider_telemetry import summarize_provider_calls

SEMANTIC_GRADE_SYSTEM_PROMPT = """\
You are a rigorous mathematical referee evaluating whether Lean theorem code is
a faithful, non-trivial formalization of an English economics claim.

Score the semantic alignment from 1 to 5:
- 5: Faithful and non-trivial translation of the claim.
- 4: Mostly faithful, with only minor simplifications.
- 3: Partially faithful or noticeably oversimplified.
- 2: Weak match, major omissions, or likely semantic distortion.
- 1: Wrong, vacuous, or auto-trivialized into something like A = A.

Be skeptical of theorem statements that:
- Drop economically meaningful assumptions or conclusions
- Replace a substantive claim with a tautology
- Formalize only a tiny algebraic fragment of the original
- Change quantifiers, domains, or the direction of the claim

Return JSON only with exactly these keys:
{
  "score": <integer 1-5>,
  "verdict": "<short label>",
  "rationale": "<2-4 sentence justification>",
  "trivialization_flags": ["<flag>", "..."]
}
"""


def _strip_json_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def _normalize_grade(payload: dict[str, Any]) -> dict[str, Any]:
    score = payload.get("score")
    if not isinstance(score, int) or not 1 <= score <= 5:
        raise ValueError(f"Semantic score must be an integer in [1, 5], got: {score!r}")

    verdict = str(payload.get("verdict", "")).strip() or "unlabeled"
    rationale = str(payload.get("rationale", "")).strip() or "No rationale provided."
    flags = payload.get("trivialization_flags", [])
    if not isinstance(flags, list):
        raise ValueError("trivialization_flags must be a list")

    return {
        "score": score,
        "verdict": verdict,
        "rationale": rationale,
        "trivialization_flags": [str(flag).strip() for flag in flags if str(flag).strip()],
        "generated": True,
    }


def grade_semantic_alignment(
    original_raw_claim: str,
    generated_theorem_code: str,
    telemetry_out: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade how faithfully Lean theorem code captures the original claim."""
    user_prompt = f"""\
Original raw claim:
{original_raw_claim.strip()}

Generated Lean theorem code:
{generated_theorem_code.strip()}
"""

    try:
        raw = call_leanstral(
            get_client(),
            [
                {"role": "system", "content": SEMANTIC_GRADE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "semantic_grade",
            temperature=0.0,
            max_tokens=700,
            telemetry_out=telemetry_out,
        )
        payload = json.loads(_strip_json_fences(raw))
        if not isinstance(payload, dict):
            raise ValueError("Semantic grader did not return a JSON object")
        result = _normalize_grade(payload)
        result["provider_telemetry"] = (
            summarize_provider_calls(telemetry_out) if telemetry_out is not None else None
        )
        return result
    except Exception as exc:
        return {
            "score": None,
            "verdict": "grading_error",
            "rationale": f"Semantic grader failed: {exc}",
            "trivialization_flags": [],
            "generated": False,
            "error": str(exc),
            "provider_telemetry": (
                summarize_provider_calls(telemetry_out) if telemetry_out is not None else None
            ),
        }
