"""
llm_client.py

Provider-agnostic LLM chat wrapper for LeanEcon.

Supported providers (set via the LLM_PROVIDER environment variable):
  - "mistral"   (default) — uses mistralai SDK, default model labs-leanstral-2603
  - "openai"    — uses openai SDK (pip install openai), default model gpt-4o
  - "anthropic" — uses anthropic SDK (pip install anthropic), default model claude-3-5-sonnet-20241022

Configure via environment variables:
  LLM_PROVIDER=mistral           # Which provider to use
  LLM_MODEL=labs-leanstral-2603  # Model name (overrides provider default)
  MISTRAL_API_KEY=...            # Required when LLM_PROVIDER=mistral
  OPENAI_API_KEY=...             # Required when LLM_PROVIDER=openai
  ANTHROPIC_API_KEY=...          # Required when LLM_PROVIDER=anthropic

Note: The agentic proving loop uses Mistral's Conversations API (run_async).
For other providers in the agentic prover, register a custom prover backend via
prover_backend.register_prover().  Non-agentic components (formalize, classify,
explain, assumptions) support all three providers above.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Constants and defaults
# ---------------------------------------------------------------------------

_PROVIDER_DEFAULTS: dict[str, str] = {
    "mistral": "labs-leanstral-2603",
    "openai": "gpt-4o",
    "anthropic": "claude-3-5-sonnet-20241022",
}

MAX_RETRIES = 2
MAX_RETRIES_RATE_LIMIT = 4


def get_llm_provider() -> str:
    """Return the active LLM provider name (lowercase).  Defaults to 'mistral'."""
    return os.environ.get("LLM_PROVIDER", "mistral").lower().strip()


def get_llm_model() -> str:
    """Return the active LLM model name from env, falling back to provider default."""
    provider = get_llm_provider()
    env_model = os.environ.get("LLM_MODEL", "").strip()
    if env_model:
        return env_model
    return _PROVIDER_DEFAULTS.get(provider, "labs-leanstral-2603")


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------

class _MistralClientWrapper:
    """Thin wrapper around mistralai.client.Mistral for uniform call interface."""

    def __init__(self) -> None:
        from mistralai.client import Mistral  # type: ignore[import]
        self._client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    def chat_complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = self._client.chat.complete(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content


class _OpenAIClientWrapper:
    """Thin wrapper around openai.OpenAI for uniform call interface."""

    def __init__(self) -> None:
        try:
            import openai  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "LLM_PROVIDER=openai requires the 'openai' package. "
                "Install it with: pip install openai"
            ) from exc
        self._client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def chat_complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content


class _AnthropicClientWrapper:
    """Thin wrapper around anthropic.Anthropic for uniform call interface."""

    def __init__(self) -> None:
        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "LLM_PROVIDER=anthropic requires the 'anthropic' package. "
                "Install it with: pip install anthropic"
            ) from exc
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    def chat_complete(
        self,
        messages: list[dict],
        *,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        import anthropic  # type: ignore[import]

        # Anthropic separates the system message from the conversation
        system_message = ""
        conversation: list[dict] = []
        for msg in messages:
            if msg["role"] == "system":
                system_message = msg["content"]
            else:
                conversation.append({"role": msg["role"], "content": msg["content"]})

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": conversation,
        }
        if system_message:
            kwargs["system"] = system_message
        # Anthropic requires temperature in [0, 1]
        kwargs["temperature"] = min(max(temperature, 0.0), 1.0)

        response = self._client.messages.create(**kwargs)
        return response.content[0].text


def create_chat_client() -> Any:
    """
    Create and return a chat client for the configured LLM provider.

    The returned object exposes a ``chat_complete(messages, *, model, temperature,
    max_tokens)`` method that returns the model's reply as a plain string.
    """
    provider = get_llm_provider()
    if provider == "mistral":
        return _MistralClientWrapper()
    if provider == "openai":
        return _OpenAIClientWrapper()
    if provider == "anthropic":
        return _AnthropicClientWrapper()
    raise ValueError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        f"Supported values: mistral, openai, anthropic."
    )


# ---------------------------------------------------------------------------
# Generic retry wrapper
# ---------------------------------------------------------------------------

def _is_rate_limit_error(exc: Exception) -> bool:
    """Return True for 429 / 503 / rate-limit errors across all providers."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status in (429, 503):
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg or "overloaded" in msg


def call_llm(
    client: Any,
    messages: list[dict],
    stage: str,
    *,
    model: str | None = None,
    temperature: float = 1.0,
    max_tokens: int = 32000,
    retry_delay_seconds: float = 5.0,
) -> str:
    """
    Call the LLM with retry logic (exponential backoff on 429/503).

    Args:
        client:      A client object returned by ``create_chat_client()``.
        messages:    OpenAI-style message list.
        stage:       Human-readable name for logging (e.g. "formalize").
        model:       Model override; defaults to ``get_llm_model()``.
        temperature: Sampling temperature.
        max_tokens:  Maximum tokens to generate.
        retry_delay_seconds: Base delay for non-rate-limit retries.

    Returns:
        The model's reply as a plain string.
    """
    if model is None:
        model = get_llm_model()

    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES_RATE_LIMIT + 1):
        try:
            return client.chat_complete(
                messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            last_error = exc
            is_rate_limit = _is_rate_limit_error(exc)
            max_attempts = MAX_RETRIES_RATE_LIMIT if is_rate_limit else MAX_RETRIES
            print(f"  [llm_client] {stage} attempt {attempt}/{max_attempts} failed: {exc}")
            if attempt >= max_attempts:
                break
            if is_rate_limit:
                delay = 2**attempt  # 2, 4, 8, 16 s
                print(f"  [llm_client] Rate limited — backing off {delay}s")
                time.sleep(delay)
            else:
                time.sleep(retry_delay_seconds)

    raise RuntimeError(
        f"LLM API ({get_llm_provider()}/{model}) failed after {MAX_RETRIES_RATE_LIMIT} "
        f"attempts ({stage}): {last_error}"
    )
