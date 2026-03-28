"""Tests for search-assisted formalization context building."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import formalization_search
from formalization_search import (
    SearchHit,
    build_explicit_preamble_artifact,
    build_formalization_context,
    merge_explicit_preamble_artifact,
)


def test_build_context_auto_selects_preambles_and_curated_hints() -> None:
    context = build_formalization_context(
        "A strictly concave function attains a maximum on a compact set.",
        enable_mcp_retrieval=False,
    )

    assert "extreme_value_theorem" in context.preamble_names
    assert "Mathlib.Analysis.Convex.Basic" in context.candidate_imports
    assert "Mathlib.Topology.Order.Basic" in context.candidate_imports
    assert "StrictConcaveOn" in context.candidate_identifiers
    assert "IsCompact.exists_isMaxOn" in context.candidate_identifiers
    assert "IsCompact.exists_isMaxOn" in context.search_terms
    assert any("IsMaxOn" in hint for hint in context.shape_guidance)
    assert context.telemetry()["retrieval"]["source_counts"]["preamble"] >= 1
    assert context.telemetry()["retrieval"]["source_counts"]["curated"] >= 1
    assert context.selection_mode == "auto"
    assert "extreme_value_theorem" in context.advisory_preamble_names
    assert context.selected_preamble_details[0]["status"] == "strong"
    assert context.runtime_search_plan
    assert context.runtime_search_plan[0].tool == "lean_local_search"


def test_build_context_monotone_convergence_has_shape_guidance() -> None:
    context = build_formalization_context(
        "A monotone sequence bounded above converges.",
        enable_mcp_retrieval=False,
    )

    assert "Mathlib.Topology.Order.MonotoneConvergence" in context.candidate_imports
    assert "Real.tendsto_of_bddAbove_monotone" in context.candidate_identifiers
    assert "Real.tendsto_of_bddAbove_monotone" in context.search_terms
    assert any("Filter.Tendsto" in hint for hint in context.shape_guidance)


def test_build_context_power_function_surfaces_rpow_guidance() -> None:
    context = build_formalization_context(
        "A real power function with exponent p has derivative p * x^(p - 1).",
        enable_mcp_retrieval=False,
    )

    assert "Mathlib.Analysis.SpecialFunctions.Pow.Real" in context.candidate_imports
    assert "Real.rpow_natCast" in context.candidate_identifiers
    assert "Real.hasDerivAt_rpow_const" in context.candidate_identifiers
    assert "Real.rpow_natCast" in context.search_terms


def test_build_context_compact_continuity_uses_continuous_on_module() -> None:
    context = build_formalization_context(
        "A continuous function on a compact set attains a maximum.",
        enable_mcp_retrieval=False,
    )

    assert "Mathlib.Topology.ContinuousOn" in context.candidate_imports
    assert "ContinuousOn" in context.candidate_identifiers
    assert "ContinuousOn" in context.search_terms


def test_build_context_fixed_point_has_unique_shape_guidance() -> None:
    context = build_formalization_context(
        "A contraction mapping on a complete metric space has a unique fixed point.",
        enable_mcp_retrieval=False,
    )

    assert "Mathlib.Topology.MetricSpace.Contracting" in context.candidate_imports
    assert "ContractingWith.fixedPoint_unique" in context.candidate_identifiers
    assert "ContractingWith.fixedPoint_unique" in context.search_terms
    assert any("∃! x, f x = x" in hint for hint in context.shape_guidance)


def test_build_context_explicit_preambles_override_auto_selection() -> None:
    context = build_formalization_context(
        "Under CRRA utility, relative risk aversion simplifies to gamma.",
        explicit_preamble_names=["discount_factor"],
        enable_mcp_retrieval=False,
    )

    assert context.preamble_names == ["discount_factor"]
    assert context.explicit_preamble_names == ["discount_factor"]
    assert context.auto_preamble_names == []
    assert context.selection_mode == "explicit"
    assert "discount_factor" in context.telemetry()["selected_preambles"]


def test_build_context_crra_auto_selection_avoids_cara_noise() -> None:
    context = build_formalization_context(
        "Under CRRA utility, relative risk aversion simplifies to gamma.",
        enable_mcp_retrieval=False,
    )

    assert "crra_utility" in context.auto_preamble_names
    assert "cara_utility" not in context.auto_preamble_names
    assert len(context.auto_preamble_names) <= 2


def test_build_context_cobb_auto_selection_avoids_ces_noise() -> None:
    context = build_formalization_context(
        "For a two-factor Cobb-Douglas production function, "
        "output elasticity with respect to capital is alpha.",
        enable_mcp_retrieval=False,
    )

    assert "cobb_douglas_2factor" in context.auto_preamble_names
    assert "ces_2factor" not in context.auto_preamble_names


def test_build_context_demotes_compatibility_only_solow_to_advisory() -> None:
    context = build_formalization_context(
        "In the Solow model, the steady state depends on savings and depreciation.",
        enable_mcp_retrieval=False,
    )

    assert "solow_steady_state" in context.advisory_preamble_names
    assert "solow_steady_state" not in context.auto_preamble_names


def test_build_context_skips_mcp_when_temporarily_unavailable() -> None:
    with patch(
        "formalization_search.formalization_mcp_available",
        return_value=(False, "cooldown"),
    ):
        context = build_formalization_context(
            "A metric contraction has a fixed point.",
            enable_mcp_retrieval=True,
        )

    assert context.telemetry()["retrieval"]["source_counts"]["mcp"] == 0
    assert context.telemetry()["mcp"]["enabled"] is False
    assert context.telemetry()["mcp"]["skip_reason"] == "cooldown"


def test_build_context_rejects_unknown_explicit_preambles() -> None:
    with pytest.raises(ValueError, match="Unknown preamble_names"):
        build_formalization_context(
            "Under CRRA utility, relative risk aversion simplifies to gamma.",
            explicit_preamble_names=["definitely_not_real"],
            enable_mcp_retrieval=False,
        )


def test_formalization_context_artifact_preserves_selected_preambles_and_validation() -> None:
    context = build_formalization_context(
        "Under CRRA utility, relative risk aversion simplifies to gamma.",
        explicit_preamble_names=["crra_utility"],
        enable_mcp_retrieval=False,
    )

    artifact = context.artifact(
        validation_method="lean_run_code",
        validation_methods=["lean_run_code"],
        validation_fallback_reasons=[],
        repair_buckets=["unknown_identifier"],
        deterministic_repairs_applied=["normalize_imports"],
    )

    assert artifact["selected_preambles"] == ["crra_utility"]
    assert artifact["explicit_preambles"] == ["crra_utility"]
    assert artifact["selection_mode"] == "explicit"
    assert artifact["selected_preamble_details"][0]["status"] == "strong"
    assert artifact["validation"]["method"] == "lean_run_code"
    assert artifact["repairs"]["repair_buckets"] == ["unknown_identifier"]


def test_build_explicit_preamble_artifact_is_minimal_but_preserves_intent() -> None:
    artifact = build_explicit_preamble_artifact(["crra_utility"])

    assert artifact["selected_preambles"] == ["crra_utility"]
    assert artifact["explicit_preambles"] == ["crra_utility"]
    assert artifact["selection_mode"] == "explicit"
    assert artifact["preamble_imports"] == ["import LeanEcon.Preamble.Consumer.CRRAUtility"]
    assert artifact["selected_preamble_details"][0]["status"] == "strong"


def test_build_explicit_preamble_artifact_preserves_compatibility_only_entries() -> None:
    artifact = build_explicit_preamble_artifact(["solow_steady_state"])

    assert artifact["selected_preambles"] == ["solow_steady_state"]
    assert artifact["explicit_preambles"] == ["solow_steady_state"]
    assert artifact["selected_preamble_details"][0]["status"] == "compatibility-only"


def test_merge_explicit_preamble_artifact_rejects_mismatch() -> None:
    with pytest.raises(ValueError, match="must exactly match"):
        merge_explicit_preamble_artifact(
            {"selected_preambles": ["cara_utility"]},
            explicit_preamble_names=["crra_utility"],
        )


def test_build_context_enabled_runtime_retrieval_surfaces_search_plan_and_hits() -> None:
    fake_hits = [
        SearchHit(
            source="lean_local_search",
            query="ContractingWith.fixedPoint_unique",
            text="ContractingWith.fixedPoint_unique ...",
        )
    ]
    with patch("formalization_search.formalization_mcp_available", return_value=(True, None)):
        with patch("formalization_search._query_mcp_hits", return_value=(fake_hits, None)):
            context = build_formalization_context(
                "A contraction mapping on a complete metric space has a unique fixed point.",
                enable_mcp_retrieval=True,
            )

    telemetry = context.telemetry()
    assert context.mcp_requested is True
    assert telemetry["mcp"]["requested"] is True
    assert telemetry["mcp"]["enabled"] is True
    assert telemetry["retrieval"]["runtime_search_plan"]
    assert any(
        directive["tool"] == "lean_local_search"
        for directive in telemetry["retrieval"]["runtime_search_plan"]
    )
    assert telemetry["mcp"]["hits"][0]["query"] == "ContractingWith.fixedPoint_unique"


def test_build_context_cached_tool_error_preserves_skip_reason_and_mcp_disabled() -> None:
    async def fake_async(_directives):
        return ([], ["tool failed: boom"])

    formalization_search._FORMALIZATION_MCP_SEARCH_CACHE.clear()
    try:
        with patch("formalization_search.formalization_mcp_available", return_value=(True, None)):
            with patch("formalization_search._query_mcp_hits_async", fake_async):
                first = build_formalization_context(
                    "A contraction mapping on a complete metric space has a unique fixed point.",
                    enable_mcp_retrieval=True,
                )
                second = build_formalization_context(
                    "A contraction mapping on a complete metric space has a unique fixed point.",
                    enable_mcp_retrieval=True,
                )
    finally:
        formalization_search._FORMALIZATION_MCP_SEARCH_CACHE.clear()

    assert first.mcp_enabled is False
    assert first.mcp_skip_reason == "tool failed: boom"
    assert second.mcp_enabled is False
    assert second.mcp_skip_reason == "tool failed: boom"
