"""
Shared Leanstral API helpers.

This module contains the generic retrying chat wrapper and output cleanup logic
used by LeanEcon components that call Leanstral outside the agentic proving
loop.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from mistralai.client import Mistral

from model_config import LEANSTRAL_MODEL

load_dotenv(Path(__file__).parent.parent / ".env")

DEFAULT_TEMPERATURE = 1.0
DEFAULT_MAX_TOKENS = 32000
MAX_RETRIES = 2
MAX_RETRIES_RATE_LIMIT = 4
RETRY_DELAY_SECONDS = 5


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception indicates a 429 or 503 (rate limit / overloaded)."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in (429, 503):
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


def get_client() -> Mistral:
    """Create a fresh authenticated Mistral client."""
    return Mistral(api_key=os.environ["MISTRAL_API_KEY"])


def strip_fences(text: str) -> str:
    """
    Clean model output by removing markdown fences and stray leading noise.

    The model occasionally prefixes output with a token count or other text
    before the first Lean-looking line.
    """
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.strip()

    lines = text.splitlines()
    lean_start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and (
            stripped.startswith(
                ("import", "open", "theorem", "lemma", "def", "example", "--", "/-", "by", "·", "#")
            )
            or re.match(r"^[a-zA-Z_\u00C0-\u024F\u1E00-\u1EFF]", stripped)
        ):
            lean_start = i
            break
    return "\n".join(lines[lean_start:]).strip()


def call_leanstral(
    client: Mistral,
    messages: list[dict],
    stage: str,
    *,
    model: str = LEANSTRAL_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Send messages to Leanstral with retry logic (exponential backoff on 429/503)."""
    last_error = None
    max_attempts = MAX_RETRIES
    for attempt in range(1, MAX_RETRIES_RATE_LIMIT + 1):
        try:
            response = client.chat.complete(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as exc:
            last_error = exc
            is_rate_limit = _is_rate_limit_error(exc)
            max_attempts = MAX_RETRIES_RATE_LIMIT if is_rate_limit else MAX_RETRIES
            print(f"  [leanstral] {stage} attempt {attempt}/{max_attempts} failed: {exc}")
            if attempt >= max_attempts:
                break
            if is_rate_limit:
                delay = 2**attempt  # 2, 4, 8, 16s
                print(f"  [leanstral] Rate limited — backing off {delay}s")
                time.sleep(delay)
            else:
                time.sleep(RETRY_DELAY_SECONDS)

    raise RuntimeError(
        f"Leanstral API failed after {max_attempts} attempts ({stage}): {last_error}"
    )
