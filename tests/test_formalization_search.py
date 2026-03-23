"""Tests for search-assisted formalization context building."""

from __future__ import annotations

from unittest.mock import patch

from formalization_search import build_formalization_context


def test_build_context_auto_selects_preambles_and_curated_hints() -> None:
    context = build_formalization_context(
        "A strictly concave function attains a maximum on a compact set."
    )

    assert "extreme_value_theorem" in context.preamble_names
    assert "Mathlib.Analysis.Convex.Basic" in context.candidate_imports
    assert "Mathlib.Topology.Order.Basic" in context.candidate_imports
    assert "StrictConcaveOn" in context.candidate_identifiers
    assert "IsCompact.exists_isMaxOn" in context.candidate_identifiers
    assert context.telemetry()["retrieval"]["source_counts"]["preamble"] >= 1
    assert context.telemetry()["retrieval"]["source_counts"]["curated"] >= 1


def test_build_context_explicit_preambles_override_auto_selection() -> None:
    context = build_formalization_context(
        "Under CRRA utility, relative risk aversion simplifies to gamma.",
        explicit_preamble_names=["discount_factor"],
    )

    assert context.preamble_names == ["discount_factor"]
    assert context.explicit_preamble_names == ["discount_factor"]
    assert context.auto_preamble_names == []
    assert "discount_factor" in context.telemetry()["selected_preambles"]


def test_build_context_skips_mcp_when_temporarily_unavailable() -> None:
    with patch(
        "formalization_search.formalization_mcp_available",
        return_value=(False, "cooldown"),
    ):
        context = build_formalization_context("A metric contraction has a fixed point.")

    assert context.telemetry()["retrieval"]["source_counts"]["mcp"] == 0
    assert context.telemetry()["mcp"]["enabled"] is False
    assert context.telemetry()["mcp"]["skip_reason"] == "cooldown"
