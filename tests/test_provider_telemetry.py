"""Unit tests for provider telemetry normalization and summarization."""

from __future__ import annotations

import provider_telemetry


def test_build_provider_call_telemetry_estimates_costs_from_usage() -> None:
    usage = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}
    telemetry = provider_telemetry.build_provider_call_telemetry(
        endpoint="chat.complete",
        model="leanstral",
        usage=usage,
        latency_ms=12.34,
        retry_count=2,
    )

    expected_base = round(
        (
            usage["prompt_tokens"] * provider_telemetry.DEFAULT_INPUT_USD_PER_1K_TOKENS
            + usage["completion_tokens"] * provider_telemetry.DEFAULT_OUTPUT_USD_PER_1K_TOKENS
        )
        / 1000.0,
        6,
    )
    expected_stress = round(
        expected_base * provider_telemetry.DEFAULT_STRESS_MULTIPLIER,
        6,
    )

    assert telemetry["endpoint"] == "chat.complete"
    assert telemetry["model"] == "leanstral"
    assert telemetry["raw_usage"] == usage
    assert telemetry["usage_present"] is True
    assert telemetry["latency_ms"] == 12.3
    assert telemetry["retry_count"] == 2
    assert telemetry["local_only"] is False
    assert telemetry["estimated_cost_base_usd"] == expected_base
    assert telemetry["estimated_cost_stress_usd"] == expected_stress


def test_build_provider_call_telemetry_local_only_is_null_safe() -> None:
    telemetry = provider_telemetry.build_provider_call_telemetry(
        endpoint="lean_compile",
        model="local_lean_compiler",
        usage=None,
        latency_ms=7.89,
        retry_count=0,
        local_only=True,
    )

    assert telemetry["raw_usage"] is None
    assert telemetry["usage_present"] is False
    assert telemetry["estimated_cost_base_usd"] is None
    assert telemetry["estimated_cost_stress_usd"] is None
    assert telemetry["local_only"] is True


def test_build_provider_call_telemetry_counts_connector_tokens_as_input() -> None:
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "connector_tokens": 30,
        "total_tokens": 150,
    }

    telemetry = provider_telemetry.build_provider_call_telemetry(
        endpoint="chat.complete",
        model="leanstral",
        usage=usage,
        latency_ms=10.0,
        retry_count=0,
    )

    expected_base = round(
        (
            (usage["prompt_tokens"] + usage["connector_tokens"])
            * provider_telemetry.DEFAULT_INPUT_USD_PER_1K_TOKENS
            + usage["completion_tokens"] * provider_telemetry.DEFAULT_OUTPUT_USD_PER_1K_TOKENS
        )
        / 1000.0,
        6,
    )

    assert telemetry["estimated_cost_base_usd"] == expected_base


def test_summarize_provider_calls_keeps_cost_null_when_any_llm_usage_is_missing() -> None:
    priced_call = provider_telemetry.build_provider_call_telemetry(
        endpoint="chat.complete",
        model="leanstral",
        usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        latency_ms=5.0,
        retry_count=0,
    )
    unpriced_call = provider_telemetry.build_provider_call_telemetry(
        endpoint="chat.complete",
        model="leanstral",
        usage={"metadata_only": True},
        latency_ms=4.0,
        retry_count=0,
    )

    summary = provider_telemetry.summarize_provider_calls([priced_call, unpriced_call])

    assert summary["provider_call_count"] == 2
    assert summary["llm_call_count"] == 2
    assert summary["usage_present"] is True
    assert summary["estimated_cost_base_usd"] is None
    assert summary["estimated_cost_stress_usd"] is None


def test_collect_and_summarize_provider_calls() -> None:
    llm_call = provider_telemetry.build_provider_call_telemetry(
        endpoint="chat.complete",
        model="leanstral",
        usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        latency_ms=5.0,
        retry_count=1,
    )
    local_call = provider_telemetry.build_provider_call_telemetry(
        endpoint="lean_compile",
        model="local_lean_compiler",
        usage=None,
        latency_ms=1.0,
        retry_count=0,
        local_only=True,
    )

    collected = provider_telemetry.collect_provider_calls(
        {"provider_calls": [llm_call]},
        {"provider_calls": [local_call]},
    )
    summary = provider_telemetry.summarize_provider_calls(collected)

    assert len(collected) == 2
    assert collected[0]["endpoint"] == "chat.complete"
    assert summary["provider_call_count"] == 2
    assert summary["llm_call_count"] == 1
    assert summary["local_only_call_count"] == 1
    assert summary["usage_present_rate"] == 1.0
    assert summary["usage_present"] is True
    assert summary["local_only"] is False
    assert summary["endpoint_counts"]["chat.complete"] == 1
    assert summary["endpoint_counts"]["lean_compile"] == 1
    assert summary["estimated_cost_base_usd"] == llm_call["estimated_cost_base_usd"]
    assert summary["estimated_cost_stress_usd"] == llm_call["estimated_cost_stress_usd"]
