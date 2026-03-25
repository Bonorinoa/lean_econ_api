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
from typing import Any

from dotenv import load_dotenv
from mistralai.client import Mistral

from model_config import LEANSTRAL_MODEL
from provider_telemetry import build_provider_call_telemetry

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

    fenced_match = re.search(r"```(?:[a-zA-Z0-9_+-]+)?\n(?P<body>.*?)```", text, flags=re.DOTALL)
    if fenced_match:
        text = fenced_match.group("body").strip()
    else:
        text = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
        text = text.strip()

    lines = text.splitlines()
    lean_start = 0
    lean_prefixes = (
        "import",
        "open",
        "theorem",
        "lemma",
        "example",
        "def",
        "noncomputable",
        "namespace",
        "section",
        "variable",
        "--",
        "/-",
        "#",
    )
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and stripped.startswith(lean_prefixes):
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
    endpoint: str = "chat.complete",
    telemetry_out: list[dict[str, Any]] | None = None,
) -> str:
    """Send messages to Leanstral with retry logic (exponential backoff on 429/503)."""
    last_error: Exception | None = None
    response = None
    retry_count = 0
    started_at = time.perf_counter()
    max_attempts = MAX_RETRIES
    try:
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
                retry_count += 1
                if is_rate_limit:
                    delay = 2**attempt  # 2, 4, 8, 16s
                    print(f"  [leanstral] Rate limited — backing off {delay}s")
                    time.sleep(delay)
                else:
                    time.sleep(RETRY_DELAY_SECONDS)
    finally:
        if telemetry_out is not None:
            telemetry_out.append(
                build_provider_call_telemetry(
                    endpoint=endpoint,
                    model=str(getattr(response, "model", model)) if response is not None else model,
                    usage=getattr(response, "usage", None) if response is not None else None,
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                    retry_count=retry_count,
                    local_only=False,
                    error=str(last_error) if last_error is not None and response is None else None,
                )
            )

    raise RuntimeError(
        f"Leanstral API failed after {max_attempts} attempts ({stage}): {last_error}"
    )
