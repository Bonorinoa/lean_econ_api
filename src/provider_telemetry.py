"""Provider usage telemetry and conservative cost estimation helpers."""

from __future__ import annotations

import copy
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

# Planning assumptions only. Keep these configurable and do not treat them as
# public pricing promises.
DEFAULT_INPUT_USD_PER_1K_TOKENS = float(
    os.environ.get("LEANECON_LLM_INPUT_USD_PER_1K_TOKENS", "0.0025")
)
DEFAULT_OUTPUT_USD_PER_1K_TOKENS = float(
    os.environ.get("LEANECON_LLM_OUTPUT_USD_PER_1K_TOKENS", "0.0075")
)
DEFAULT_STRESS_MULTIPLIER = float(os.environ.get("LEANECON_LLM_STRESS_MULTIPLIER", "1.5"))


def _jsonable(value: Any) -> Any:
    """Convert SDK or pydantic payloads into JSON-safe Python values."""
    if value is None:
        return None

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return model_dump(mode="python")
        except TypeError:
            return model_dump()

    if isinstance(value, dict):
        return {str(key): _jsonable(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return {
            str(key): _jsonable(inner)
            for key, inner in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def _positive_int(value: Any) -> int | None:
    """Return a non-negative integer when the payload provides one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def normalize_usage_payload(raw_usage: Any) -> dict[str, Any] | None:
    """Normalize raw SDK usage payloads into plain dictionaries."""
    if raw_usage is None:
        return None

    payload = _jsonable(raw_usage)
    if isinstance(payload, dict):
        return payload
    return {"value": payload}


def estimate_cost_bounds(
    usage_payload: Mapping[str, Any] | None,
) -> tuple[float | None, float | None]:
    """Estimate conservative nominal and stress costs from provider usage."""
    if not usage_payload:
        return None, None

    prompt_tokens = _positive_int(usage_payload.get("prompt_tokens"))
    completion_tokens = _positive_int(usage_payload.get("completion_tokens"))
    total_tokens = _positive_int(usage_payload.get("total_tokens"))
    connector_tokens = _positive_int(usage_payload.get("connector_tokens"))

    if prompt_tokens is not None and completion_tokens is not None:
        input_tokens = prompt_tokens + (connector_tokens or 0)
        base_cost = (
            input_tokens * DEFAULT_INPUT_USD_PER_1K_TOKENS
            + completion_tokens * DEFAULT_OUTPUT_USD_PER_1K_TOKENS
        ) / 1000.0
    elif total_tokens is not None:
        blended_rate = (DEFAULT_INPUT_USD_PER_1K_TOKENS + DEFAULT_OUTPUT_USD_PER_1K_TOKENS) / 2
        base_cost = total_tokens * blended_rate / 1000.0
    else:
        return None, None

    stress_cost = base_cost * DEFAULT_STRESS_MULTIPLIER
    return round(base_cost, 6), round(stress_cost, 6)


def build_provider_call_telemetry(
    *,
    endpoint: str,
    model: str | None,
    usage: Any,
    latency_ms: float,
    retry_count: int,
    local_only: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a normalized telemetry record for a single provider call."""
    raw_usage = normalize_usage_payload(usage)
    base_cost: float | None = None
    stress_cost: float | None = None
    if not local_only:
        base_cost, stress_cost = estimate_cost_bounds(raw_usage)

    telemetry: dict[str, Any] = {
        "endpoint": endpoint,
        "model": model,
        "raw_usage": raw_usage,
        "usage_present": raw_usage is not None,
        "latency_ms": round(float(latency_ms), 1),
        "retry_count": int(retry_count),
        "local_only": local_only,
        "estimated_cost_base_usd": base_cost,
        "estimated_cost_stress_usd": stress_cost,
    }
    if error is not None:
        telemetry["error"] = str(error)
    return telemetry


def collect_provider_calls(*sources: Any) -> list[dict[str, Any]]:
    """Flatten provider call lists from one or more telemetry-bearing objects."""
    provider_calls: list[dict[str, Any]] = []
    for source in sources:
        if source is None:
            continue
        raw_calls: Any = None
        if isinstance(source, Mapping):
            raw_calls = source.get("provider_calls")
        elif isinstance(source, Sequence) and not isinstance(source, (str, bytes, bytearray)):
            raw_calls = source
        if not isinstance(raw_calls, Sequence) or isinstance(raw_calls, (str, bytes, bytearray)):
            continue
        for call in raw_calls:
            if isinstance(call, Mapping):
                provider_calls.append(copy.deepcopy(dict(call)))
    return provider_calls


def summarize_provider_calls(
    provider_calls: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Summarize a list of provider calls into conservative aggregate telemetry."""
    calls = [
        copy.deepcopy(dict(call)) for call in provider_calls or [] if isinstance(call, Mapping)
    ]
    llm_calls = [call for call in calls if not call.get("local_only")]
    local_only_calls = [call for call in calls if call.get("local_only")]

    endpoint_counts = Counter(str(call.get("endpoint")) for call in calls if call.get("endpoint"))
    model_counts = Counter(str(call.get("model")) for call in calls if call.get("model"))
    retry_count_total = sum(int(call.get("retry_count", 0)) for call in calls)
    retry_count_max = max((int(call.get("retry_count", 0)) for call in calls), default=0)
    latency_ms_total = (
        round(
            sum(float(call.get("latency_ms", 0.0)) for call in calls),
            1,
        )
        if calls
        else 0.0
    )

    usage_present_count = sum(1 for call in llm_calls if call.get("usage_present"))
    usage_present_rate = round(usage_present_count / len(llm_calls), 3) if llm_calls else None
    usage_present = bool(llm_calls) and usage_present_count == len(llm_calls)

    base_costs = [call.get("estimated_cost_base_usd") for call in llm_calls]
    stress_costs = [call.get("estimated_cost_stress_usd") for call in llm_calls]
    estimated_cost_base_usd = (
        round(sum(float(cost) for cost in base_costs), 6)
        if llm_calls and all(cost is not None for cost in base_costs)
        else None
    )
    estimated_cost_stress_usd = (
        round(sum(float(cost) for cost in stress_costs), 6)
        if llm_calls and all(cost is not None for cost in stress_costs)
        else None
    )

    return {
        "provider_calls": calls,
        "provider_call_count": len(calls),
        "llm_call_count": len(llm_calls),
        "local_only_call_count": len(local_only_calls),
        "usage_present_count": usage_present_count,
        "usage_present_rate": usage_present_rate,
        "usage_present": usage_present,
        "endpoint_counts": dict(endpoint_counts),
        "model_counts": dict(model_counts),
        "retry_count_total": retry_count_total,
        "retry_count_max": retry_count_max,
        "latency_ms_total": latency_ms_total,
        "estimated_cost_base_usd": estimated_cost_base_usd,
        "estimated_cost_stress_usd": estimated_cost_stress_usd,
        "local_only": len(llm_calls) == 0,
    }
