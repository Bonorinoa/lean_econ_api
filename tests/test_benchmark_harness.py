"""Tests for the benchmark harness and CLI wrapper."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import benchmark_harness
import provider_telemetry as telemetry_helpers


def _fake_pipeline_result(
    *,
    success: bool,
    stop_reason: str | None = None,
    proof_generated: bool = True,
    phase: str | None = None,
    from_cache: bool = False,
    partial: bool = False,
    provider_telemetry: dict | None = None,
) -> dict:
    return {
        "success": success,
        "lean_code": "import Mathlib\n\ntheorem bench : True := by trivial\n",
        "errors": [] if success else ["synthetic failure"],
        "warnings": [],
        "proof_strategy": "synthetic",
        "proof_tactics": "trivial",
        "theorem_statement": "import Mathlib\n\ntheorem bench : True := by sorry\n",
        "formalization_attempts": 0,
        "formalization_failed": False,
        "failure_reason": None,
        "output_lean": None,
        "proof_generated": proof_generated,
        "phase": phase or ("verified" if success else "failed"),
        "elapsed_seconds": 0.25,
        "from_cache": from_cache,
        "partial": partial,
        "stop_reason": stop_reason,
        "attempts_used": 1,
        "tool_trace": [],
        "tactic_calls": [],
        "trace_schema_version": 2,
        "agent_summary": "",
        "agent_elapsed_seconds": 0.25,
        "axiom_info": None,
        "provider_telemetry": (
            provider_telemetry or telemetry_helpers.summarize_provider_calls([])
        ),
    }


def _fake_formalizer_telemetry(
    *,
    validation_method: str = "lake_env_lean",
    repair_buckets: list[str] | None = None,
) -> dict:
    provider_calls = [
        {
            "endpoint": "chat.complete",
            "model": "formalizer",
            "raw_usage": {"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
            "usage_present": True,
            "latency_ms": 12.5,
            "retry_count": 0,
            "local_only": False,
            "estimated_cost_base_usd": 0.001,
            "estimated_cost_stress_usd": 0.0015,
        }
    ]
    return {
        "model_calls": 1,
        "validation_method": validation_method,
        "validation_methods": [validation_method],
        "validation_fallback_reasons": [],
        "repair_buckets": list(repair_buckets or []),
        "last_repair_bucket": (repair_buckets or [None])[-1],
        "deterministic_repairs_applied": [],
        "retrieval": {
            "source_counts": {"preamble": 1, "curated": 2, "mcp": 0},
            "candidate_imports": ["Mathlib.Analysis.Convex.Basic"],
            "candidate_identifiers": ["StrictConcaveOn"],
            "search_terms": ["IsCompact.exists_isMaxOn"],
            "shape_guidance": ["Use `∃ x ∈ s, IsMaxOn f s x` for maximum claims."],
        },
        "provider_telemetry": telemetry_helpers.summarize_provider_calls(provider_calls),
    }


def _fake_semantic_alignment(score: int = 5) -> dict:
    provider_calls = [
        {
            "endpoint": "semantic_grade",
            "model": "semantic-grader",
            "raw_usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
            "usage_present": True,
            "latency_ms": 8.0,
            "retry_count": 0,
            "local_only": False,
            "estimated_cost_base_usd": 0.001,
            "estimated_cost_stress_usd": 0.0015,
        }
    ]
    return {
        "score": score,
        "verdict": "faithful",
        "rationale": "Synthetic semantic alignment result.",
        "trivialization_flags": [],
        "generated": True,
        "provider_telemetry": telemetry_helpers.summarize_provider_calls(provider_calls),
    }


def _fake_proving_provider_telemetry() -> dict:
    provider_calls = [
        {
            "endpoint": "conversations.start_async",
            "model": "leanstral",
            "raw_usage": {"prompt_tokens": 120, "completion_tokens": 20, "total_tokens": 140},
            "usage_present": True,
            "latency_ms": 15.0,
            "retry_count": 0,
            "local_only": False,
            "estimated_cost_base_usd": 0.001,
            "estimated_cost_stress_usd": 0.0015,
        },
        {
            "endpoint": "conversations.append_async",
            "model": "leanstral",
            "raw_usage": {"prompt_tokens": 80, "completion_tokens": 30, "total_tokens": 110},
            "usage_present": True,
            "latency_ms": 9.5,
            "retry_count": 0,
            "local_only": False,
            "estimated_cost_base_usd": 0.001,
            "estimated_cost_stress_usd": 0.0015,
        },
    ]
    return telemetry_helpers.summarize_provider_calls(provider_calls)


def test_load_benchmark_cases_preserves_optional_metadata(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "tier0.jsonl"
    theorem_stub = "import Mathlib\n\ntheorem one_plus_one : 1 + 1 = 2 := by\n  sorry\n"
    benchmark_path.write_text(
        json.dumps(
            {
                "id": "tier0_one_plus_one",
                "tier": "tier0_smoke",
                "raw_claim": "1 + 1 = 2",
                "theorem_stub": theorem_stub,
                "raw_lean": theorem_stub,
                "expected_category": "ALGEBRAIC",
                "preamble_names": [],
                "provenance": {
                    "source_path": "tests/fixtures/claims/test_claims.jsonl",
                    "source_kind": "fixture",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    cases = benchmark_harness.load_benchmark_cases(benchmark_path)

    assert len(cases) == 1
    case = cases[0]
    assert case.id == "tier0_one_plus_one"
    assert case.tier == "tier0_smoke"
    assert case.expected_category == "ALGEBRAIC"
    assert case.provenance == {
        "source_path": "tests/fixtures/claims/test_claims.jsonl",
        "source_kind": "fixture",
    }
    assert case.applicable_lanes() == [
        benchmark_harness.LANE_RAW_CLAIM_FULL_API,
        benchmark_harness.LANE_THEOREM_STUB_VERIFY,
        benchmark_harness.LANE_RAW_LEAN_VERIFY,
    ]


def test_main_writes_snapshot_and_report_with_separate_lane_metrics(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "tier0.jsonl"
    output_root = tmp_path / "benchmark_outputs"
    benchmark_path.write_text(
        json.dumps(
            {
                "id": "bench_001",
                "tier": "tier0_smoke",
                "raw_claim": "Claim A",
                "theorem_stub": "STUB_A",
                "raw_lean": "RAW_A",
                "expected_category": "ALGEBRAIC",
                "preamble_names": ["budget_set"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    theorem_stub_attempts = {"count": 0}

    def fake_formalize_claim(raw_claim: str, on_log=None, preamble_names=None, use_cache=True):
        assert raw_claim == "Claim A"
        assert preamble_names == ["budget_set"]
        assert use_cache is False
        if on_log:
            on_log({"stage": "formalize", "status": "done", "message": "formalized"})
        return {
            "success": True,
            "theorem_code": "FORMALIZED_A",
            "attempts": 1,
            "errors": [],
            "formalization_failed": False,
            "failure_reason": None,
            "preamble_used": ["budget_set"],
            "diagnosis": None,
            "suggested_fix": None,
            "fixable": None,
            "formalizer_telemetry": _fake_formalizer_telemetry(),
        }

    def fake_run_pipeline(
        *,
        raw_input: str,
        preformalized_theorem: str | None = None,
        on_log=None,
        use_cache: bool,
    ):
        assert use_cache is False
        if preformalized_theorem == "FORMALIZED_A":
            if on_log:
                on_log({"stage": "agentic_verify", "status": "done", "message": "verified"})
            return _fake_pipeline_result(
                success=True,
                phase="verified",
                provider_telemetry=_fake_proving_provider_telemetry(),
            )

        if preformalized_theorem == "STUB_A":
            theorem_stub_attempts["count"] += 1
            if theorem_stub_attempts["count"] < 3:
                if on_log:
                    on_log(
                        {
                            "stage": "agentic_run",
                            "status": "error",
                            "message": "retryable failure",
                        }
                    )
                return _fake_pipeline_result(
                    success=False,
                    stop_reason="proof_incomplete",
                    proof_generated=False,
                    phase="failed",
                    provider_telemetry=_fake_proving_provider_telemetry(),
                )
            if on_log:
                on_log({"stage": "agentic_verify", "status": "done", "message": "verified"})
            return _fake_pipeline_result(
                success=True,
                phase="verified",
                provider_telemetry=_fake_proving_provider_telemetry(),
            )

        assert raw_input == "RAW_A"
        assert preformalized_theorem is None
        if on_log:
            on_log({"stage": "agentic_verify", "status": "error", "message": "timed out"})
        return _fake_pipeline_result(
            success=False,
            stop_reason="timeout",
            proof_generated=False,
            phase="failed",
            partial=True,
            provider_telemetry=_fake_proving_provider_telemetry(),
        )

    argv = [
        "run_benchmark.py",
        str(benchmark_path),
        "--repetitions",
        "3",
        "--no-cache",
        "--output-root",
        str(output_root),
    ]
    with (
        patch.object(benchmark_harness, "formalize_claim", side_effect=fake_formalize_claim),
        patch.object(
            benchmark_harness,
            "grade_semantic_alignment",
            return_value=_fake_semantic_alignment(),
        ),
        patch.object(benchmark_harness, "run_pipeline", side_effect=fake_run_pipeline),
        patch.object(sys, "argv", argv),
        patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}, clear=False),
    ):
        exit_code = benchmark_harness.main()

    assert exit_code == 0
    snapshot_files = list((output_root / "snapshots").glob("*.json"))
    report_files = list((output_root / "reports").glob("*.md"))
    assert len(snapshot_files) == 1
    assert len(report_files) == 1

    payload = json.loads(snapshot_files[0].read_text(encoding="utf-8"))
    lane_summary = payload["summary"]["lanes"]
    by_tier = payload["summary"]["by_tier"]
    assert payload["config"]["use_cache"] is False
    assert payload["snapshot_schema_version"] == 4
    assert lane_summary["raw_claim_full_api"]["pass_at_1"] == 1.0
    assert lane_summary["raw_claim_full_api"]["pass_at_3"] == 1.0
    assert lane_summary["raw_claim_full_api"]["partial_attempts"] == 0
    assert lane_summary["raw_claim_full_api"]["partial_rate"] == 0.0
    assert lane_summary["raw_claim_full_api"]["validation_method_counts"]["lake_env_lean"] == 3
    assert lane_summary["raw_claim_full_api"]["retrieval_source_counts"]["curated"] == 6
    assert lane_summary["raw_claim_full_api"]["semantic_alignment"]["graded_attempts"] == 3
    assert lane_summary["raw_claim_full_api"]["semantic_alignment"]["score_ge_4_rate"] == 1.0
    assert lane_summary["raw_claim_full_api"]["provider_call_count"] == 12
    assert lane_summary["raw_claim_full_api"]["llm_call_count"] == 12
    assert lane_summary["raw_claim_full_api"]["usage_present"] is True
    assert lane_summary["raw_claim_full_api"]["local_only"] is False
    assert lane_summary["raw_claim_full_api"]["estimated_cost_base_usd"] == 0.012
    assert lane_summary["raw_claim_full_api"]["estimated_cost_stress_usd"] == 0.018
    assert lane_summary["theorem_stub_verify"]["pass_at_1"] == 0.0
    assert lane_summary["theorem_stub_verify"]["pass_at_3"] == 1.0
    assert lane_summary["theorem_stub_verify"]["partial_attempts"] == 0
    assert lane_summary["theorem_stub_verify"]["partial_rate"] == 0.0
    assert lane_summary["theorem_stub_verify"]["provider_call_count"] == 6
    assert lane_summary["theorem_stub_verify"]["estimated_cost_base_usd"] == 0.006
    assert lane_summary["raw_lean_verify"]["pass_at_3"] == 0.0
    assert lane_summary["raw_lean_verify"]["partial_attempts"] == 3
    assert lane_summary["raw_lean_verify"]["partial_rate"] == 1.0
    assert lane_summary["raw_lean_verify"]["error_code_counts"]["proof_timeout"] == 3
    assert lane_summary["raw_lean_verify"]["failure_stage_counts"]["agentic_verify"] == 3
    assert lane_summary["raw_lean_verify"]["provider_call_count"] == 6
    assert lane_summary["raw_lean_verify"]["estimated_cost_base_usd"] == 0.006
    assert by_tier["tier0_smoke"]["lanes"]["raw_claim_full_api"]["pass_at_1"] == 1.0
    assert by_tier["tier0_smoke"]["lanes"]["raw_lean_verify"]["partial_rate"] == 1.0

    case_record = payload["cases"][0]
    assert case_record["lanes"]["theorem_stub_verify"]["summary"]["pass_at_3"] is True
    assert case_record["lanes"]["raw_lean_verify"]["summary"]["stop_reason_counts"]["timeout"] == 3
    assert case_record["lanes"]["raw_lean_verify"]["summary"]["partial_attempts"] == 3
    assert case_record["lanes"]["raw_lean_verify"]["summary"]["partial_rate"] == 1.0
    assert case_record["lanes"]["raw_claim_full_api"]["summary"]["provider_call_count"] == 12
    assert (
        case_record["lanes"]["raw_claim_full_api"]["attempts"][0]["formalizer_telemetry"][
            "validation_method"
        ]
        == "lake_env_lean"
    )

    report_text = report_files[0].read_text(encoding="utf-8")
    assert "LeanEcon Benchmark Report" in report_text
    assert "raw_claim -> full API" in report_text
    assert "Partial attempts" in report_text
    assert "partial_rate=1.0" in report_text
    assert "Aggregate Tier Summary" in report_text
    assert "bench_001" in report_text


def test_formalizer_only_mode_skips_verify_lanes(tmp_path: Path) -> None:
    benchmark_path = tmp_path / "tier1.jsonl"
    output_root = tmp_path / "benchmark_outputs"
    benchmark_path.write_text(
        json.dumps(
            {
                "id": "bench_formalizer",
                "tier": "tier1_core",
                "raw_claim": "Formalize only claim",
                "expected_category": "DEFINABLE",
                "preamble_names": ["discount_factor"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    def fake_formalize_claim(raw_claim: str, on_log=None, preamble_names=None, use_cache=True):
        assert use_cache is False
        if on_log:
            on_log({"stage": "formalize", "status": "done", "message": "formalized"})
        return {
            "success": True,
            "theorem_code": "import Mathlib\n\ntheorem fast_gate : True := by\n  sorry\n",
            "attempts": 1,
            "errors": [],
            "formalization_failed": False,
            "failure_reason": None,
            "preamble_used": list(preamble_names or []),
            "diagnosis": None,
            "suggested_fix": None,
            "fixable": None,
            "formalizer_telemetry": _fake_formalizer_telemetry(
                validation_method="lean_run_code",
                repair_buckets=["unknown_identifier"],
            ),
        }

    argv = [
        "run_benchmark.py",
        str(benchmark_path),
        "--mode",
        "formalizer-only",
        "--output-root",
        str(output_root),
    ]
    with (
        patch.object(benchmark_harness, "formalize_claim", side_effect=fake_formalize_claim),
        patch.object(
            benchmark_harness,
            "grade_semantic_alignment",
            return_value=_fake_semantic_alignment(score=4),
        ),
        patch.object(benchmark_harness, "run_pipeline") as mock_run_pipeline,
        patch.object(sys, "argv", argv),
        patch.dict("os.environ", {"MISTRAL_API_KEY": "test-key"}, clear=False),
    ):
        exit_code = benchmark_harness.main()

    assert exit_code == 0
    mock_run_pipeline.assert_not_called()
    snapshot_path = next((output_root / "snapshots").glob("*.json"))
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert list(payload["summary"]["lanes"]) == ["formalizer_only"]
    assert payload["summary"]["lanes"]["formalizer_only"]["pass_at_1"] == 1.0
    assert payload["summary"]["lanes"]["formalizer_only"]["partial_attempts"] == 0
    assert payload["summary"]["lanes"]["formalizer_only"]["partial_rate"] == 0.0
    assert payload["summary"]["lanes"]["formalizer_only"]["validation_method_counts"] == {
        "lean_run_code": 3
    }
    assert payload["summary"]["lanes"]["formalizer_only"]["provider_call_count"] == 6
    assert payload["summary"]["lanes"]["formalizer_only"]["usage_present"] is True
    assert payload["summary"]["lanes"]["formalizer_only"]["local_only"] is False
    assert payload["summary"]["lanes"]["formalizer_only"]["estimated_cost_base_usd"] == 0.006
    assert (
        payload["summary"]["lanes"]["formalizer_only"]["semantic_alignment"]["graded_attempts"] == 3
    )
    assert payload["summary"]["lanes"]["formalizer_only"]["repair_bucket_counts"] == {
        "unknown_identifier": 3
    }


def test_benchmark_output_root_respects_state_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LEANECON_STATE_DIR", str(tmp_path))

    assert benchmark_harness.benchmark_output_root() == tmp_path / "benchmarks"


def test_load_latest_snapshot_uses_state_dir_and_bundled_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    state_dir = tmp_path / "state"
    bundled_root = tmp_path / "bundled"
    state_snapshots = state_dir / "benchmarks" / "snapshots"
    bundled_snapshots = bundled_root / "snapshots"
    state_snapshots.mkdir(parents=True)
    bundled_snapshots.mkdir(parents=True)

    bundled_snapshot = bundled_snapshots / "bundled.json"
    bundled_snapshot.write_text(
        json.dumps({"generated_at": "2026-03-23T00:00:00+00:00", "summary": {"total_cases": 1}}),
        encoding="utf-8",
    )
    time.sleep(0.01)
    state_snapshot = state_snapshots / "state.json"
    state_snapshot.write_text(
        json.dumps({"generated_at": "2026-03-24T00:00:00+00:00", "summary": {"total_cases": 2}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("LEANECON_STATE_DIR", str(state_dir))
    monkeypatch.setattr(benchmark_harness, "DEFAULT_OUTPUT_ROOT", bundled_root)

    latest = benchmark_harness.load_latest_snapshot()

    assert latest is not None
    assert latest["generated_at"] == "2026-03-24T00:00:00+00:00"
    assert latest["summary"]["total_cases"] == 2


def test_latest_snapshot_summary_omits_case_details(monkeypatch, tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    snapshot_path = snapshot_dir / "latest.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-25T00:00:00+00:00",
                "benchmark_file": "benchmarks/tier1_core_selected_full.jsonl",
                "config": {"mode": "full", "repetitions": 1, "use_cache": False},
                "summary": {"total_cases": 3},
                "cases": [{"id": "bench_001"}],
            }
        ),
        encoding="utf-8",
    )

    summary = benchmark_harness.latest_snapshot_summary(snapshot_dir=snapshot_dir)

    assert summary is not None
    assert summary["generated_at"] == "2026-03-25T00:00:00+00:00"
    assert summary["benchmark_file"] == "benchmarks/tier1_core_selected_full.jsonl"
    assert summary["summary"]["total_cases"] == 3
    assert "cases" not in summary
