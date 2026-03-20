"""
Batch proof generation via Leanstral. For agentic proving, see
agentic_prover.py.
"""

import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from mistralai.client import Mistral

# Load .env from the project root (one level up from src/)
load_dotenv(Path(__file__).parent.parent / ".env")

MODEL = "labs-leanstral-2603"
TEMPERATURE = 1.0
MAX_TOKENS = 32000
MAX_RETRIES = 2
RETRY_DELAY = 5  # seconds between retries
_client: Mistral | None = None

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

STRATEGY_SYSTEM_PROMPT = """\
You are an expert in Lean 4 and the Mathlib library.
You will be given a Lean 4 theorem statement with `sorry` as a placeholder.
Your task is to describe a proof strategy in plain English — which tactics,
lemmas, or mathematical steps would be needed to close the goal.
Be concise (3-8 sentences). Do NOT write any Lean code yet.

When analyzing the goal:
- If it's pure field arithmetic (+, -, *, /, ⁻¹), plan field_simp + ring.
- If it contains variable-exponent ^ (Real.rpow), note that rpow needs
  dedicated lemmas after field_simp, not ring alone.
- If it involves Real.log, plan to use log lemmas for cancellation.
- If it's an ∃ or ↔ goal, plan the structural decomposition first.
"""

PROOF_SYSTEM_PROMPT = """\
You are an expert in Lean 4 and the Mathlib library.
You will be given a Lean 4 theorem statement and a proof strategy.
Your task is to write the complete Lean 4 tactic proof.

Rules:
- Output ONLY the `by` tactic block (everything after `:= by`).
  Do NOT repeat the theorem statement or imports.
- Use standard Mathlib tactics: ring, norm_num, simp, nlinarith,
  field_simp, linarith, push_neg, positivity, etc.
- If helper lemmas are needed, write them BEFORE the main theorem,
  including their full signatures and proofs.
- Do NOT use `sorry`.
- Do NOT include markdown fences or explanatory text — only Lean code.

TACTIC GUIDANCE BY GOAL SHAPE:

1. Pure field arithmetic (goals with +, -, *, /, ⁻¹, no variable-exponent ^):
   Use `field_simp [ne_of_gt hX, ...]` to clear denominators, then `ring`.

2. Goals with Real.rpow / variable-exponent ^ (e.g., K ^ α, c ^ (-γ)):
   `ring` and `field_simp` do NOT understand rpow. After clearing fractions
   with field_simp, use rpow lemmas (rpow_add, rpow_one, rpow_sub, rpow_neg,
   mul_rpow) to combine/cancel exponents, then ring_nf or congr 1; ring.

3. Goals with Real.log:
   Use `Real.log_mul`, `Real.log_div`, `Real.log_rpow`, `Real.log_inv`.
   Often `ring_nf` suffices after log terms cancel.

4. Existential goals (∃ x, P x):
   Use `use <witness>` to provide the witness, then prove P.

5. Biconditional goals (P ↔ Q):
   Use `constructor` to split into forward and backward directions,
   then prove each separately.
"""

FEEDBACK_STRATEGY_PROMPT = """\
You are an expert in Lean 4 and the Mathlib library.
A previous proof attempt for the theorem below FAILED.

You will be given:
1. The Lean 4 theorem statement
2. The previous proof attempt that failed
3. The Lean 4 error messages and goal state from `lake build`

Analyze WHY the proof failed, then describe a REVISED proof strategy
that avoids the same mistakes. If the error shows unsolved goals or a
residual goal state, your new strategy must target THAT specific goal,
not the original theorem statement.

Be concise (3-8 sentences). Do NOT write any Lean code yet.
"""

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_client() -> Mistral:
    """Create the shared Mistral client lazily."""
    global _client
    if _client is None:
        _client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    return _client


def _strip_fences(text: str) -> str:
    """
    Clean model output: remove markdown fences and any non-Lean preamble.

    The model sometimes prefixes output with a token count or stray number.
    We drop everything before the first line that looks like Lean code.
    """
    text = text.strip()
    # Remove opening fence with optional language tag
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    # Remove closing fence
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    # Drop leading lines that don't look like Lean (e.g. a stray "4" or blank)
    lines = text.splitlines()
    lean_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        # A Lean line starts with a keyword, operator, or unicode identifier
        if stripped and (
            stripped.startswith(("import", "open", "theorem", "lemma", "def",
                                  "example", "--", "/-", "by", "·", "#"))
            or re.match(r"^[a-zA-Z_\u00C0-\u024F\u1E00-\u1EFF]", stripped)
        ):
            lean_start = i
            break
    return "\n".join(lines[lean_start:]).strip()


def call_leanstral(
    client: Mistral,
    messages: list[dict],
    stage: str,
    temperature: float = TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> str:
    """
    Send messages to the Leanstral API with retry logic.

    Public so formalizer.py can reuse this without duplicating retry logic.

    Args:
        client: Authenticated Mistral client.
        messages: List of {role, content} dicts.
        stage: Human-readable label for logging ("strategy", "proof", "formalize", etc.).
        temperature: Sampling temperature (default TEMPERATURE=1.0).
        max_tokens: Max tokens to generate (default MAX_TOKENS=32000).

    Returns:
        Raw text content from the model response.

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.complete(
                model=MODEL,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            last_error = e
            print(f"  [leanstral] {stage} attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)

    raise RuntimeError(
        f"Leanstral API failed after {MAX_RETRIES} attempts ({stage}): {last_error}"
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_proof_strategy(theorem_with_sorry: str) -> str:
    """
    Stage 1: Ask Leanstral to describe a proof strategy in plain English.

    Args:
        theorem_with_sorry: Full Lean 4 theorem statement with `sorry` body.
            Example:
                theorem crra_rra (γ : ℝ) (hγ : γ > 0) (c : ℝ) (hc : c > 0) :
                  -c * (-γ * c⁻¹) = γ := by
                  sorry

    Returns:
        Plain-English proof strategy (3-8 sentences).
    """
    client = _get_client()
    messages = [
        {"role": "system", "content": STRATEGY_SYSTEM_PROMPT},
        {"role": "user", "content": theorem_with_sorry},
    ]
    return call_leanstral(client, messages, "strategy")


def generate_proof(theorem_with_sorry: str, strategy: str) -> str:
    """
    Stage 2: Ask Leanstral to generate a complete tactic proof given a strategy.

    Args:
        theorem_with_sorry: Full Lean 4 theorem statement with `sorry` body.
        strategy: Plain-English proof strategy from Stage 1.

    Returns:
        Lean 4 tactic block (everything that replaces `sorry`).
        Markdown fences are stripped automatically.
    """
    client = _get_client()
    user_content = f"""\
Theorem:
{theorem_with_sorry}

Proof strategy:
{strategy}

Now write the complete Lean 4 proof.
"""
    messages = [
        {"role": "system", "content": PROOF_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    raw = call_leanstral(client, messages, "proof")
    if len(raw.strip()) < 80:
        print(f"[leanstral] WARNING: suspiciously short proof ({len(raw.strip())} chars) — raw: {raw!r}")
    return _strip_fences(raw)


def prove_theorem(theorem_with_sorry: str) -> dict:
    """
    Full two-stage proof generation pipeline.

    Args:
        theorem_with_sorry: Lean 4 theorem statement with `sorry` placeholder.

    Returns:
        dict with keys:
          - strategy (str): Plain-English proof plan from Stage 1.
          - proof_tactics (str): Lean 4 tactic block from Stage 2.
          - full_lean_code (str): Complete .lean file content ready for verification.
    """
    print("[leanstral] Stage 1: generating proof strategy...")
    strategy = get_proof_strategy(theorem_with_sorry)
    print(f"[leanstral] Strategy: {strategy[:200]}{'...' if len(strategy) > 200 else ''}")

    print("[leanstral] Stage 2: generating tactic proof...")
    proof_tactics = generate_proof(theorem_with_sorry, strategy)
    print(f"[leanstral] Got proof ({len(proof_tactics)} chars)")

    # Replace `sorry` in the theorem statement with the generated tactics
    full_lean_code = _assemble_lean_file(theorem_with_sorry, proof_tactics)

    return {
        "strategy": strategy,
        "proof_tactics": proof_tactics,
        "full_lean_code": full_lean_code,
    }


def prove_theorem_with_feedback(
    theorem_with_sorry: str,
    previous_error: str,
    previous_proof: str,
) -> dict:
    """
    Two-stage proof generation with feedback from a prior failed attempt.

    Stage 1: Generate a revised strategy informed by the previous failure.
    Stage 2: Generate proof tactics from the revised strategy.

    Args:
        theorem_with_sorry: Lean 4 theorem statement with sorry.
        previous_error: Lean errors and bounded build output from the failed verification.
        previous_proof: The proof tactics from the failed attempt.

    Returns:
        Same dict as prove_theorem(): {strategy, proof_tactics, full_lean_code}
    """
    client = _get_client()

    # Stage 1: feedback-informed strategy
    print("[leanstral] Stage 1 (feedback): generating revised strategy...")
    user_content = f"""\
Theorem:
{theorem_with_sorry}

Previous proof attempt (FAILED):
{previous_proof}

Lean 4 error context:
{previous_error}

Describe a revised proof strategy that avoids these errors.
"""
    messages = [
        {"role": "system", "content": FEEDBACK_STRATEGY_PROMPT},
        {"role": "user", "content": user_content},
    ]
    strategy = call_leanstral(client, messages, "feedback_strategy")
    print(f"[leanstral] Revised strategy: {strategy[:200]}{'...' if len(strategy) > 200 else ''}")

    # Stage 2: generate proof from revised strategy (reuse existing function)
    print("[leanstral] Stage 2: generating tactic proof from revised strategy...")
    proof_tactics = generate_proof(theorem_with_sorry, strategy)
    print(f"[leanstral] Got proof ({len(proof_tactics)} chars)")

    full_lean_code = _assemble_lean_file(theorem_with_sorry, proof_tactics)

    return {
        "strategy": strategy,
        "proof_tactics": proof_tactics,
        "full_lean_code": full_lean_code,
    }


def _assemble_lean_file(theorem_with_sorry: str, proof_tactics: str) -> str:
    """
    Combine Mathlib import header, theorem statement, and generated proof tactics
    into a complete .lean file string.

    Handles three model output styles:
      1. Full file with imports — use as-is.
      2. Full theorem statement (contains `theorem`/`lemma`) — extract tactic body,
         then stitch with header + original theorem signature.
      3. Bare tactics — replace `sorry` in theorem_with_sorry.

    Args:
        theorem_with_sorry: Original theorem statement with `sorry`.
        proof_tactics: Cleaned output from Stage 2.

    Returns:
        Complete .lean file content as a string.
    """
    header = "import Mathlib\nopen Real\n\n"
    tactics = proof_tactics.strip()

    # Case 1: the model returned a complete Lean file with its own imports.
    if tactics.startswith("import"):
        return tactics

    # Case 2: the model returned a full theorem/lemma/example instead of just
    # the tactic block, so peel off everything after `:= by`.
    if re.search(r"\btheorem\b|\blemma\b|\bexample\b", tactics):
        # Pull everything after the last `:= by` occurrence.
        match = re.search(r":=\s*by\s*\n(.*)", tactics, re.DOTALL)
        if match:
            tactics = match.group(1).rstrip()
        # If no `:= by` found, use the whole thing (best-effort)

    # Case 3: the model returned bare tactics, so splice them into the original
    # theorem body where `sorry` appeared.
    base = theorem_with_sorry.strip()
    if base.startswith("import"):
        # Already has header; just replace sorry
        return re.sub(r"\n\s*sorry[^\n]*", "\n" + _indent(tactics, 2), base, count=1)

    theorem_body = re.sub(
        r"\n\s*sorry[^\n]*",
        "\n" + _indent(tactics, 2),
        base,
        count=1,
    )
    return header + theorem_body


def _indent(text: str, spaces: int) -> str:
    """Indent every line of text by `spaces` spaces."""
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.split("\n"))


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

def _test_connection():
    """
    Quick sanity test: send a trivial theorem and confirm the API responds.
    """
    trivial_theorem = """\
theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""
    try:
        result = prove_theorem(trivial_theorem)
    except Exception as exc:
        print(f"leanstral_client connection test: FAIL ({exc})")
        return

    has_strategy = bool(result["strategy"].strip())
    has_proof = bool(result["proof_tactics"].strip())
    has_file = "theorem one_plus_one" in result["full_lean_code"]
    passed = has_strategy and has_proof and has_file
    status = "PASS" if passed else "FAIL"
    print(
        "leanstral_client connection test: "
        f"{status} (strategy={'yes' if has_strategy else 'no'}, "
        f"proof={'yes' if has_proof else 'no'}, "
        f"assembled_file={'yes' if has_file else 'no'})"
    )


if __name__ == "__main__":
    _test_connection()
