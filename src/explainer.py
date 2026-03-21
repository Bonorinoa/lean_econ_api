"""Natural-language explanations for Lean verification results."""

from __future__ import annotations

import os
import queue
import threading
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from mistralai.client import Mistral

from leanstral_utils import call_leanstral

# Load .env from the project root (one level up from src/)
load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "labs-leanstral-2603"
EXPLAIN_TEMPERATURE = 0.3
EXPLAIN_MAX_TOKENS = 1024
EXPLAIN_TIMEOUT_SECONDS = 7

EXPLAIN_SYSTEM_PROMPT = """\
You are an expert at explaining formal mathematics to economists who have
never used a proof assistant.

You will be given:
1. The original claim (natural language or LaTeX)
2. The Lean 4 theorem statement
3. The proof tactics (if verification succeeded)
4. The verification outcome (verified / failed / etc.)
5. Any error messages

Write a clear, jargon-free explanation structured as follows:

## What was formalized
Restate what the Lean theorem captures in plain English. Be specific about
what variables represent and what the theorem actually says. If the
formalization simplified the original claim (e.g., reduced a derivative
to an algebraic identity), explain the simplification.

## How the proof works
(Only if verification succeeded.)
Explain what the proof tactics did in plain English. Map each major tactic
to its mathematical meaning:
- field_simp → "cleared fractions and simplified the algebra"
- ring / ring_nf → "verified the equality using algebraic rules"
- norm_num → "checked the arithmetic numerically"
- exact h → "used the hypothesis directly"
- linarith → "applied linear arithmetic reasoning"
Use Lean syntax in the explanation to enhance it pedagogically for users learning lean4. Write for someone who has never seen a proof assistant.

## What this means
(If verified:) Explain that Lean 4's type checker has verified every logical
step from axioms. This is not LLM confidence — it is a machine-checked proof.
The economist does not need to trust the LLM, only the Lean kernel.
(If failed:) Explain what went wrong in non-technical terms. Distinguish
between "the claim might be true but the prover couldn't find a proof" and
"the formalization itself had issues."

## Limitations
Briefly note what the formalization does NOT capture. For example: "This
verifies the algebraic identity after substituting the functional forms.
It does not verify that CRRA utility is the correct model for the economic
phenomenon you're studying."

Keep the total explanation under 300 words. Use short paragraphs. No bullet
points — write in prose.
"""

FALLBACK_EXPLANATIONS = {
    "classification_rejected": (
        "**Claim not supported.** This claim requires mathematical definitions "
        "that are not currently available in LeanEcon's verification scope. "
        "Try rephrasing as a direct algebraic identity, or paste a Lean 4 "
        "theorem directly."
    ),
    "verified": (
        "**Verified.** Lean 4's type checker has confirmed that the proof is "
        "logically valid from axioms. This is a machine-checked proof — not "
        "an LLM's opinion, but a formal guarantee.\n\n"
        "The explanation service is temporarily unavailable. Review the Lean "
        "proof in the Proof tab for details."
    ),
    "proving_failed": (
        "**Proof not found.** The theorem statement compiled successfully in "
        "Lean 4, meaning it is a well-formed mathematical claim. However, the "
        "automated prover could not find a proof within the allotted attempts.\n\n"
        "This does not mean the claim is false — it means the prover needs a "
        "different approach. You can try again (proof generation is stochastic) "
        "or edit the theorem statement."
    ),
    "formalization_failed": (
        "**Could not formalize.** The system could not translate your claim "
        "into a valid Lean 4 theorem. This usually means the claim requires "
        "mathematical definitions that aren't available in Lean's math library "
        "(Mathlib), or the claim is too ambiguous to formalize automatically.\n\n"
        "Try rephrasing the claim more precisely, or paste a Lean 4 theorem "
        "directly if you have one."
    ),
    "verification_failed": (
        "**Verification rejected.** A proof was generated but Lean's type "
        "checker rejected it. This is a prover error — the proof attempt "
        "had a logical flaw. The claim itself may still be true.\n\n"
        "The prover generates proofs stochastically. Try running again for "
        "a different proof attempt."
    ),
}


def _log(
    on_log: Callable[[dict], None] | None,
    message: str,
    *,
    data: str | None = None,
    status: str = "done",
) -> None:
    """Emit explainer log entries without risking user-facing failures."""
    if not on_log:
        return
    try:
        on_log({"stage": "explain", "message": message, "data": data, "status": status})
    except Exception:
        pass


def _truncate(text: str | None, limit: int) -> str:
    """Trim text to a bounded size for prompts/logs."""
    if not text:
        return ""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "\n... (truncated)"


def _format_messages(messages: list[str], limit: int = 6) -> str:
    """Render error/warning lists into a compact prompt section."""
    cleaned = [str(message).strip() for message in messages if str(message).strip()]
    if not cleaned:
        return "(none)"
    rendered = "\n\n".join(cleaned[:limit])
    return _truncate(rendered, 2000)


def _infer_outcome_label(verification_result: dict) -> str:
    """Normalize the result dict into the fallback outcome taxonomy."""
    if verification_result.get("formalization_failed"):
        reason = verification_result.get("failure_reason", "")
        if reason and "definition" in reason.lower():
            return "classification_rejected"
        return "formalization_failed"
    if verification_result.get("success"):
        return "verified"
    if verification_result.get("proof_generated") is False:
        return "proving_failed"
    return "verification_failed"


def _build_user_prompt(
    original_claim: str,
    theorem_code: str,
    verification_result: dict,
    outcome_label: str,
) -> str:
    """Assemble the explainer user prompt from pipeline artifacts."""
    errors = list(verification_result.get("errors") or [])
    warnings = list(verification_result.get("warnings") or [])
    failure_reason = verification_result.get("failure_reason")
    if failure_reason:
        errors.insert(0, failure_reason)

    proof_tactics = verification_result.get("proof_tactics", "")
    proof_strategy = verification_result.get("proof_strategy", "")

    return f"""\
Original claim:
{_truncate(original_claim or "(none provided)", 3000)}

Lean 4 theorem statement:
{_truncate(theorem_code or verification_result.get("lean_code") or "(none available)", 4000)}

Proof tactics:
{_truncate(proof_tactics or "(none available)", 3000)}

Proof strategy:
{_truncate(proof_strategy or "(none available)", 2000)}

Verification outcome:
{outcome_label}

Errors:
{_format_messages(errors)}

Warnings:
{_format_messages(warnings)}
"""


def _call_explainer_model(user_prompt: str) -> str:
    """Run the explanation request against Leanstral."""
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    messages = [
        {"role": "system", "content": EXPLAIN_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    return call_leanstral(
        client,
        messages,
        "explain",
        temperature=EXPLAIN_TEMPERATURE,
        max_tokens=EXPLAIN_MAX_TOKENS,
    ).strip()


def _call_with_timeout(user_prompt: str) -> str:
    """Run the model call in a daemon thread so the UI can bail out quickly."""
    result_queue: queue.Queue[tuple[str, str | Exception]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put(("result", _call_explainer_model(user_prompt)))
        except Exception as exc:
            result_queue.put(("error", exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    try:
        kind, payload = result_queue.get(timeout=EXPLAIN_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        raise TimeoutError(
            f"Explanation request exceeded {EXPLAIN_TIMEOUT_SECONDS:.1f}s"
        ) from exc

    if kind == "error":
        raise payload
    return payload


def explain_result(
    original_claim: str,
    theorem_code: str,
    verification_result: dict,
    on_log: Callable[[dict], None] | None = None,
) -> dict:
    """
    Generate a natural language explanation of the verification result.

    Args:
        original_claim: The user's original input (LaTeX/text/raw Lean).
        theorem_code: The Lean 4 theorem with sorry (pre-proof).
        verification_result: Output of prove_and_verify().
        on_log: Optional pipeline log callback.

    Returns:
        dict with keys:
          - explanation (str): Markdown-formatted explanation.
          - generated (bool): True if LLM generated it, False if fallback.
    """
    outcome_label = "verification_failed"
    try:
        verification_result = verification_result or {}
        outcome_label = _infer_outcome_label(verification_result)
        user_prompt = _build_user_prompt(
            original_claim=original_claim,
            theorem_code=theorem_code,
            verification_result=verification_result,
            outcome_label=outcome_label,
        )

        _log(
            on_log,
            f"Calling {MODEL} to generate explanation...",
            status="running",
        )
        explanation = _call_with_timeout(user_prompt)
        if not explanation:
            raise RuntimeError("Leanstral returned an empty explanation")

        _log(
            on_log,
            "Explanation generated",
            data=_truncate(explanation, 1200),
            status="done",
        )
        return {"explanation": explanation, "generated": True}
    except Exception as exc:
        fallback = FALLBACK_EXPLANATIONS.get(
            outcome_label,
            FALLBACK_EXPLANATIONS["verification_failed"],
        )
        _log(
            on_log,
            "Explanation unavailable — using fallback",
            data=str(exc),
            status="error",
        )
        return {"explanation": fallback, "generated": False}
