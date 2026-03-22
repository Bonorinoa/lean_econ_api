"""
assumption_detector.py

Identifies implicit (unstated) assumptions in economic claims or text.

Given any input in text form (plain English, LaTeX, or a mix), this module
uses the configured LLM to surface the mathematical, economic, and modelling
assumptions that are being made without being stated explicitly.

Public API:
  detect_assumptions(text, *, on_log=None) -> dict
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

from llm_client import call_llm, create_chat_client, get_llm_model

load_dotenv(Path(__file__).parent.parent / ".env")

ASSUMPTION_TEMPERATURE = 0.2  # low temperature for deterministic, focused output
ASSUMPTION_MAX_TOKENS = 2048

ASSUMPTION_SYSTEM_PROMPT = """\
You are an expert in mathematical economics and economic theory at the PhD level.

Your task is to identify ALL implicit assumptions embedded in the given text.
Implicit assumptions are claims that the author treats as true without stating
them explicitly, but that are required for the argument or result to hold.

Analyse the input from three angles:

1. MATHEMATICAL ASSUMPTIONS
   Conditions required for the mathematics to work:
   - Domain restrictions (e.g. "c > 0 is required for log utility")
   - Smoothness / differentiability (e.g. "utility must be twice differentiable")
   - Interiority conditions (e.g. "optimal consumption must be interior")
   - Boundedness / compactness (e.g. "budget set must be compact for maximum to exist")
   - Measure-theory requirements (e.g. "probability space must be well-defined")

2. ECONOMIC ASSUMPTIONS
   Behavioural, institutional, or structural premises:
   - Market structure (e.g. "perfect competition assumed: price-taking agents")
   - Information structure (e.g. "symmetric information assumed")
   - Rationality and optimisation (e.g. "agents maximise expected utility")
   - Preference axioms (e.g. "preferences are complete and transitive")
   - Functional form assumptions (e.g. "Cobb-Douglas technology is CRS by construction")
   - Static vs. dynamic framing (e.g. "no intertemporal trade-offs assumed")
   - Equilibrium concept (e.g. "Walrasian equilibrium assumed; no strategic interaction")

3. MODELLING ASSUMPTIONS
   Simplifications that restrict generality:
   - Finite vs. infinite agents/goods
   - Deterministic vs. stochastic environment
   - Representative-agent framework
   - Homogeneity of agents
   - Absence of externalities, public goods, etc.

OUTPUT FORMAT — return a JSON object with this exact schema:
{
  "mathematical_assumptions": [
    {"assumption": "...", "reason": "..."}
  ],
  "economic_assumptions": [
    {"assumption": "...", "reason": "..."}
  ],
  "modelling_assumptions": [
    {"assumption": "...", "reason": "..."}
  ],
  "overall_summary": "2-3 sentence summary of the most consequential implicit assumptions"
}

Rules:
- Each assumption must be specific and actionable, not a platitude.
- Explain briefly WHY each item is an implicit assumption (not stated in the text).
- If a category has no implicit assumptions, return an empty array for that key.
- Do NOT include assumptions that are explicitly stated in the input.
- Output ONLY the JSON object. No markdown fences, no preamble, no explanation outside the JSON.
"""


def detect_assumptions(
    text: str,
    *,
    on_log=None,
) -> dict:
    """
    Detect implicit assumptions in the given text.

    Args:
        text:   Plain text, LaTeX, or a mix describing an economic claim,
                model, or argument.
        on_log: Optional pipeline log callback ``(dict) -> None``.

    Returns:
        dict with keys:
          - mathematical_assumptions (list[dict]):  Each has "assumption" and "reason".
          - economic_assumptions (list[dict]):       Each has "assumption" and "reason".
          - modelling_assumptions (list[dict]):      Each has "assumption" and "reason".
          - overall_summary (str):                   High-level summary.
          - generated (bool):                        True if LLM generated the result.
          - error (str | None):                      Error message if generation failed.
    """
    import json as _json

    def _log(message: str, *, status: str = "done", data: str | None = None) -> None:
        if on_log:
            try:
                on_log({"stage": "assumptions", "message": message, "data": data, "status": status})
            except Exception:
                pass

    if not text or not text.strip():
        return _empty_result(error="Input text is empty.")

    _log("Detecting implicit assumptions...", status="running")
    try:
        client = create_chat_client()
        messages = [
            {"role": "system", "content": ASSUMPTION_SYSTEM_PROMPT},
            {"role": "user", "content": text.strip()},
        ]
        raw = call_llm(
            client,
            messages,
            "assumptions",
            temperature=ASSUMPTION_TEMPERATURE,
            max_tokens=ASSUMPTION_MAX_TOKENS,
        )
        # Strip potential markdown fences before JSON parsing
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            cleaned = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            ).strip()

        parsed = _json.loads(cleaned)
        result = {
            "mathematical_assumptions": list(parsed.get("mathematical_assumptions") or []),
            "economic_assumptions": list(parsed.get("economic_assumptions") or []),
            "modelling_assumptions": list(parsed.get("modelling_assumptions") or []),
            "overall_summary": str(parsed.get("overall_summary") or "").strip(),
            "generated": True,
            "error": None,
        }
        total = (
            len(result["mathematical_assumptions"])
            + len(result["economic_assumptions"])
            + len(result["modelling_assumptions"])
        )
        _log(
            f"Identified {total} implicit assumption(s)",
            status="done",
            data=result["overall_summary"],
        )
        return result

    except _json.JSONDecodeError as exc:
        _log("JSON parse error in assumption detection", status="error", data=str(exc))
        return _empty_result(error=f"Failed to parse LLM output as JSON: {exc}")
    except Exception as exc:
        _log("Assumption detection failed", status="error", data=str(exc))
        return _empty_result(error=f"Assumption detection failed: {exc}")


def _empty_result(*, error: str | None = None) -> dict:
    return {
        "mathematical_assumptions": [],
        "economic_assumptions": [],
        "modelling_assumptions": [],
        "overall_summary": "",
        "generated": False,
        "error": error,
    }
