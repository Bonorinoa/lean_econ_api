"""
Standalone smoke tests for the FastAPI service.

Usage:
  python tests/test_api_smoke.py
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

import api

RAW_LEAN_THEOREM = """\
import Mathlib
open Real

theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""


def _run_case(name: str, fn) -> bool:
    try:
        fn()
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False
    print(f"{name}: PASS")
    return True


def _make_verify_result() -> dict:
    return {
        "success": True,
        "lean_code": RAW_LEAN_THEOREM.replace("sorry", "norm_num"),
        "errors": [],
        "warnings": [],
        "proof_strategy": "Use norm_num.",
        "proof_tactics": "norm_num",
        "theorem_statement": RAW_LEAN_THEOREM.strip(),
        "formalization_attempts": 0,
        "formalization_failed": False,
        "failure_reason": None,
        "output_lean": None,
        "proof_generated": True,
        "phase": "verified",
        "elapsed_seconds": 0.1,
        "from_cache": False,
        "partial": False,
        "stop_reason": None,
        "attempts_used": 1,
        "tool_trace": [],
        "tactic_calls": [],
        "agent_summary": "Leanstral agentic prover: 1 API round-trips, 1 tactic applications.",
        "agent_elapsed_seconds": 0.1,
        "axiom_info": None,
        "error_code": "none",
    }


# ---------------------------------------------------------------------------
# Existing tests (updated for v1 paths)
# ---------------------------------------------------------------------------

def _test_app_imports_and_routes() -> None:
    route_paths = {route.path for route in api.app.routes}
    # v1 versioned routes
    assert "/api/v1/classify" in route_paths
    assert "/api/v1/formalize" in route_paths
    assert "/api/v1/verify" in route_paths
    assert "/api/v1/jobs/{job_id}" in route_paths
    assert "/api/v1/jobs/{job_id}/stream" in route_paths
    assert "/api/v1/explain" in route_paths
    assert "/api/v1/metrics" in route_paths
    assert "/api/v1/cache/stats" in route_paths
    assert "/api/v1/cache" in route_paths
    # meta
    assert "/health" in route_paths


def _test_health() -> None:
    client = TestClient(api.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _test_cors_middleware_present() -> None:
    middleware_names = {middleware.cls.__name__ for middleware in api.app.user_middleware}
    assert "CORSMiddleware" in middleware_names


def _test_classify_raw_lean() -> None:
    client = TestClient(api.app)
    response = client.post("/api/v1/classify", json={"raw_claim": RAW_LEAN_THEOREM})
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "RAW_LEAN"
    assert body["formalizable"] is True
    assert body["is_raw_lean"] is True
    assert body["error_code"] == "none"


def _test_classify_requires_definitions() -> None:
    client = TestClient(api.app)
    with patch.object(
        api,
        "classify_claim",
        return_value={
            "category": "REQUIRES_DEFINITIONS",
            "reason": "Needs domain-specific economic definitions.",
            "definitions_needed": None,
            "preamble_matches": [],
            "suggested_reformulation": None,
        },
    ):
        response = client.post(
            "/api/v1/classify",
            json={"raw_claim": "The second welfare theorem holds under convex preferences."},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "REQUIRES_DEFINITIONS"
    assert body["formalizable"] is False
    assert "definitions" in body["reason"].lower()


def _test_formalize_raw_lean_bypass() -> None:
    client = TestClient(api.app)
    response = client.post("/api/v1/formalize", json={"raw_claim": RAW_LEAN_THEOREM})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["attempts"] == 0
    assert body["formalization_failed"] is False
    assert body["theorem_code"] == RAW_LEAN_THEOREM.strip()


def _test_verify_exceptions_return_500() -> None:
    client = TestClient(api.app, raise_server_exceptions=False)
    with patch.object(api, "run_pipeline", side_effect=RuntimeError("boom")):
        # First submit
        resp = client.post("/api/v1/verify", json={"theorem_code": RAW_LEAN_THEOREM})
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        # Poll for failed status
        for _ in range(20):
            status_resp = client.get(f"/api/v1/jobs/{job_id}")
            assert status_resp.status_code == 200
            data = status_resp.json()
            if data["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)
        assert data["status"] == "failed"
        assert "boom" in data["error"]


def _test_openapi_schema() -> None:
    client = TestClient(api.app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/verify" in schema["paths"]
    assert "/api/v1/jobs/{job_id}/stream" in schema["paths"]
    assert "/api/v1/metrics" in schema["paths"]
    assert "VerifyRequest" in schema["components"]["schemas"]
    assert "VerifyAcceptedResponse" in schema["components"]["schemas"]
    assert "JobStatusResponse" in schema["components"]["schemas"]


# ---------------------------------------------------------------------------
# New tests: error codes
# ---------------------------------------------------------------------------

def _test_error_codes_on_failure() -> None:
    client = TestClient(api.app)
    with patch.object(
        api,
        "classify_claim",
        return_value={
            "category": "REQUIRES_DEFINITIONS",
            "reason": "Needs domain-specific economic definitions.",
            "definitions_needed": None,
            "preamble_matches": [],
            "suggested_reformulation": None,
        },
    ):
        response = client.post(
            "/api/v1/classify",
            json={"raw_claim": "The second welfare theorem holds under convex preferences."},
        )
    assert response.status_code == 200
    assert response.json()["error_code"] == "classification_rejected"


def _test_error_codes_on_success() -> None:
    client = TestClient(api.app)
    response = client.post("/api/v1/classify", json={"raw_claim": RAW_LEAN_THEOREM})
    assert response.status_code == 200
    assert response.json()["error_code"] == "none"


# ---------------------------------------------------------------------------
# New tests: async verify
# ---------------------------------------------------------------------------

def _test_verify_returns_202_with_job_id() -> None:
    client = TestClient(api.app)
    with patch.object(api, "run_pipeline", return_value=_make_verify_result()):
        response = client.post("/api/v1/verify", json={"theorem_code": RAW_LEAN_THEOREM})
    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    assert body["status"] == "queued"


def _test_verify_uses_preformalized_theorem() -> None:
    client = TestClient(api.app)
    captured: dict[str, str] = {}

    def fake_run_pipeline(*, raw_input: str, preformalized_theorem: str, on_log=None) -> dict:
        captured["raw_input"] = raw_input
        captured["preformalized_theorem"] = preformalized_theorem
        return _make_verify_result()

    with patch.object(api, "run_pipeline", side_effect=fake_run_pipeline):
        response = client.post("/api/v1/verify", json={"theorem_code": RAW_LEAN_THEOREM})

    assert response.status_code == 202
    body = response.json()
    assert "job_id" in body
    job_id = body["job_id"]

    # Poll until completed
    for _ in range(20):
        status_resp = client.get(f"/api/v1/jobs/{job_id}")
        assert status_resp.status_code == 200
        data = status_resp.json()
        if data["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)

    assert data["status"] == "completed"
    assert data["result"]["success"] is True
    assert captured["raw_input"] == RAW_LEAN_THEOREM.strip()
    assert captured["preformalized_theorem"] == RAW_LEAN_THEOREM.strip()


def _test_job_status_queued_or_running() -> None:
    client = TestClient(api.app)

    # Use a slow mock so we can catch queued/running state
    import threading

    barrier = threading.Event()

    def slow_pipeline(**kwargs):
        barrier.wait(timeout=2.0)
        return _make_verify_result()

    with patch.object(api, "run_pipeline", side_effect=slow_pipeline):
        resp = client.post("/api/v1/verify", json={"theorem_code": RAW_LEAN_THEOREM})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # Job should be queued or running before we release the barrier
    status_resp = client.get(f"/api/v1/jobs/{job_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] in ("queued", "running", "completed")

    barrier.set()


def _test_job_not_found() -> None:
    client = TestClient(api.app)
    response = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def _test_stream_completed_job() -> None:
    client = TestClient(api.app)
    with patch.object(api, "run_pipeline", return_value=_make_verify_result()):
        resp = client.post("/api/v1/verify", json={"theorem_code": RAW_LEAN_THEOREM})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    for _ in range(20):
        status = client.get(f"/api/v1/jobs/{job_id}").json()
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)

    with client.stream("GET", f"/api/v1/jobs/{job_id}/stream") as response:
        assert response.status_code == 200
        body = b"".join(response.iter_bytes())

    assert b'"type": "complete"' in body or b'"type":"complete"' in body
    assert b'"status": "completed"' in body or b'"status":"completed"' in body


def _test_stream_not_found() -> None:
    client = TestClient(api.app)
    response = client.get("/api/v1/jobs/00000000-0000-0000-0000-000000000000/stream")
    assert response.status_code == 404


def _test_stream_live_progress() -> None:
    client = TestClient(api.app)
    emit_progress = threading.Event()
    complete_job = threading.Event()

    def fake_run_pipeline(*, raw_input: str, preformalized_theorem: str, on_log=None) -> dict:
        emit_progress.wait(timeout=2.0)
        if on_log is not None:
            on_log(
                {
                    "stage": "formalize",
                    "message": "Calling Leanstral...",
                    "status": "running",
                }
            )
        complete_job.wait(timeout=2.0)
        if on_log is not None:
            on_log(
                {
                    "stage": "agentic_run",
                    "message": "Leanstral proving loop finished.",
                    "status": "done",
                }
            )
        return _make_verify_result()

    job_id = api.job_store.create({"theorem_code": RAW_LEAN_THEOREM, "explain": False})

    with patch.object(api, "run_pipeline", side_effect=fake_run_pipeline):
        worker = threading.Thread(
            target=api._run_verify_job,
            args=(job_id, RAW_LEAN_THEOREM, False),
            daemon=True,
        )
        worker.start()

        with client.stream("GET", f"/api/v1/jobs/{job_id}/stream") as response:
            assert response.status_code == 200
            emit_progress.set()
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if (b'"type": "progress"' in body or b'"type":"progress"' in body) and not complete_job.is_set():
                    complete_job.set()
                if b'"type": "complete"' in body or b'"type":"complete"' in body:
                    break

        worker.join(timeout=2.0)

    assert b'"type": "progress"' in body or b'"type":"progress"' in body
    assert b'"stage": "formalize"' in body or b'"stage":"formalize"' in body
    assert b'"message": "Calling Leanstral..."' in body or b'"message":"Calling Leanstral..."' in body
    assert b'"status": "running"' in body or b'"status":"running"' in body
    assert b'"type": "complete"' in body or b'"type":"complete"' in body
    assert not worker.is_alive()


def _test_cache_stats_endpoint() -> None:
    client = TestClient(api.app)
    response = client.get("/api/v1/cache/stats")
    assert response.status_code == 200
    assert "size" in response.json()


def _test_metrics_empty_log() -> None:
    client = TestClient(api.app)
    with tempfile.TemporaryDirectory() as tmpdir:
        missing_path = Path(tmpdir) / "missing.jsonl"
        with patch.object(api, "LOG_FILE", missing_path):
            response = client.get("/api/v1/metrics")
    assert response.status_code == 200
    assert response.json() == {
        "total_runs": 0,
        "verified": 0,
        "formalization_failures": 0,
        "proof_failures": 0,
        "cache_hits": 0,
        "partial_runs": 0,
        "avg_elapsed_seconds": 0.0,
        "verification_rate": 0.0,
        "cache_hit_rate": 0.0,
    }


def _test_metrics_aggregates_runs() -> None:
    client = TestClient(api.app)
    entries = [
        {
            "verification": {"success": True},
            "formalization": {"formalization_failed": False},
            "from_cache": False,
            "partial": False,
            "elapsed_seconds": 10.0,
        },
        {
            "verification": {"success": False},
            "formalization": {"formalization_failed": True},
            "from_cache": False,
            "partial": False,
            "elapsed_seconds": 5.0,
        },
        {
            "verification": {"success": False},
            "formalization": {"formalization_failed": False},
            "from_cache": True,
            "partial": True,
            "elapsed_seconds": 15.0,
        },
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "runs.jsonl"
        lines = [json.dumps(entry) for entry in entries]
        lines.append("{bad json")
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with patch.object(api, "LOG_FILE", log_path):
            response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "total_runs": 3,
        "verified": 1,
        "formalization_failures": 1,
        "proof_failures": 1,
        "cache_hits": 1,
        "partial_runs": 1,
        "avg_elapsed_seconds": 10.0,
        "verification_rate": 0.333,
        "cache_hit_rate": 0.333,
    }


def _test_cache_clear_endpoint() -> None:
    client = TestClient(api.app)
    response = client.delete("/api/v1/cache")
    assert response.status_code == 200
    assert response.json()["status"] == "cleared"


# ---------------------------------------------------------------------------
# New tests: explain endpoint
# ---------------------------------------------------------------------------

def _test_explain_verified() -> None:
    client = TestClient(api.app)

    def fake_explain(*, original_claim, theorem_code, verification_result, on_log=None):
        return {"explanation": "The proof is valid.", "generated": False}

    with patch.object(api, "explain_result", side_effect=fake_explain):
        response = client.post(
            "/api/v1/explain",
            json={
                "original_claim": "1 + 1 = 2",
                "verification_result": {
                    "success": True,
                    "proof_generated": True,
                    "formalization_failed": False,
                },
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body["explanation"]) > 0
    assert body["error_code"] == "none"


def _test_explain_classification_rejected() -> None:
    client = TestClient(api.app)

    def fake_explain(*, original_claim, theorem_code, verification_result, on_log=None):
        return {"explanation": "Claim not supported.", "generated": False}

    with patch.object(api, "explain_result", side_effect=fake_explain):
        response = client.post(
            "/api/v1/explain",
            json={
                "original_claim": "The second welfare theorem holds.",
                "classification_result": {
                    "category": "REQUIRES_DEFINITIONS",
                    "formalizable": False,
                    "reason": "Needs domain-specific economic definitions.",
                },
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert len(body["explanation"]) > 0


def _test_explain_formalization_failed() -> None:
    client = TestClient(api.app)

    def fake_explain(*, original_claim, theorem_code, verification_result, on_log=None):
        return {"explanation": "Could not formalize.", "generated": False}

    with patch.object(api, "explain_result", side_effect=fake_explain):
        response = client.post(
            "/api/v1/explain",
            json={
                "original_claim": "Some claim",
                "formalization_result": {
                    "formalization_failed": True,
                    "failure_reason": "Requires custom definitions.",
                    "errors": [],
                },
            },
        )
    assert response.status_code == 200
    assert len(response.json()["explanation"]) > 0


# ---------------------------------------------------------------------------
# New test: legacy backward-compat
# ---------------------------------------------------------------------------

def _test_legacy_classify_still_works() -> None:
    client = TestClient(api.app)
    response = client.post("/api/classify", json={"raw_claim": RAW_LEAN_THEOREM})
    assert response.status_code == 200
    assert response.json()["category"] == "RAW_LEAN"


# ---------------------------------------------------------------------------
# Bundle 2: three-tier classifier, preamble, diagnostics
# ---------------------------------------------------------------------------

def _test_classify_definable_with_preamble() -> None:
    """DEFINABLE claims with preamble matches are formalizable."""
    client = TestClient(api.app)
    with patch.object(
        api,
        "classify_claim",
        return_value={
            "category": "DEFINABLE",
            "reason": "Needs Cobb-Douglas production function definition.",
            "definitions_needed": "Cobb-Douglas production function definition.",
            "preamble_matches": ["cobb_douglas_2factor"],
            "suggested_reformulation": "LeanEcon has built-in definitions for these.",
        },
    ):
        response = client.post(
            "/api/v1/classify",
            json={"raw_claim": "Cobb-Douglas output elasticity equals alpha."},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "DEFINABLE"
    assert body["formalizable"] is True
    assert "cobb_douglas_2factor" in body["preamble_matches"]
    assert body["suggested_reformulation"] is not None
    assert body["error_code"] == "none"


def _test_formalize_with_preamble_names() -> None:
    """Formalize endpoint threads preamble_names through."""
    client = TestClient(api.app)
    captured: dict = {}

    def fake_formalize_claim(raw_input, on_log=None, preamble_names=None):
        captured["preamble_names"] = preamble_names
        return {
            "success": True,
            "theorem_code": RAW_LEAN_THEOREM.strip(),
            "attempts": 1,
            "errors": [],
            "formalization_failed": False,
            "failure_reason": None,
            "preamble_used": preamble_names or [],
            "diagnosis": None,
            "suggested_fix": None,
            "fixable": None,
        }

    with patch.object(api, "formalize_claim", side_effect=fake_formalize_claim):
        response = client.post(
            "/api/v1/formalize",
            json={
                "raw_claim": "Cobb-Douglas output elasticity equals alpha.",
                "preamble_names": ["cobb_douglas_2factor"],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["preamble_used"] == ["cobb_douglas_2factor"]
    assert captured["preamble_names"] == ["cobb_douglas_2factor"]


def _test_formalize_failure_with_diagnosis() -> None:
    """Failed formalization includes diagnostic fields."""
    client = TestClient(api.app)

    def fake_formalize_claim(raw_input, on_log=None, preamble_names=None):
        return {
            "success": False,
            "theorem_code": "import Mathlib\nsorry",
            "attempts": 3,
            "errors": ["unknown identifier 'foo'"],
            "formalization_failed": False,
            "failure_reason": None,
            "preamble_used": [],
            "diagnosis": "The identifier 'foo' does not exist in Mathlib.",
            "suggested_fix": "Replace 'foo' with the correct Mathlib name.",
            "fixable": True,
        }

    with patch.object(api, "formalize_claim", side_effect=fake_formalize_claim):
        response = client.post(
            "/api/v1/formalize",
            json={"raw_claim": "Some claim that fails."},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["diagnosis"] is not None
    assert body["suggested_fix"] is not None
    assert body["fixable"] is True


def _test_formalize_success_no_diagnosis() -> None:
    """Successful formalization has no diagnostic fields."""
    client = TestClient(api.app)
    response = client.post("/api/v1/formalize", json={"raw_claim": RAW_LEAN_THEOREM})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["diagnosis"] is None
    assert body["preamble_used"] == []


def _test_prover_registry() -> None:
    from prover_backend import PROVER_REGISTRY, get_prover

    assert "leanstral" in PROVER_REGISTRY
    prover = get_prover("leanstral")
    assert prover.name == "leanstral"


def _test_prover_registry_unknown() -> None:
    from prover_backend import get_prover

    try:
        get_prover("nonexistent")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "nonexistent" in str(exc)


def main() -> int:
    print("=" * 60)
    print("LeanEcon FastAPI Smoke Tests")
    print("=" * 60)

    results = {
        "app_imports_and_routes": _run_case("app_imports_and_routes", _test_app_imports_and_routes),
        "health": _run_case("health", _test_health),
        "cors_middleware_present": _run_case("cors_middleware_present", _test_cors_middleware_present),
        "classify_raw_lean": _run_case("classify_raw_lean", _test_classify_raw_lean),
        "classify_requires_definitions": _run_case(
            "classify_requires_definitions",
            _test_classify_requires_definitions,
        ),
        "formalize_raw_lean_bypass": _run_case(
            "formalize_raw_lean_bypass",
            _test_formalize_raw_lean_bypass,
        ),
        "verify_exceptions_return_500": _run_case(
            "verify_exceptions_return_500",
            _test_verify_exceptions_return_500,
        ),
        "openapi_schema": _run_case("openapi_schema", _test_openapi_schema),
        # error codes
        "error_codes_on_failure": _run_case("error_codes_on_failure", _test_error_codes_on_failure),
        "error_codes_on_success": _run_case("error_codes_on_success", _test_error_codes_on_success),
        # async verify
        "verify_returns_202_with_job_id": _run_case(
            "verify_returns_202_with_job_id", _test_verify_returns_202_with_job_id
        ),
        "verify_uses_preformalized_theorem": _run_case(
            "verify_uses_preformalized_theorem",
            _test_verify_uses_preformalized_theorem,
        ),
        "job_status_queued_or_running": _run_case(
            "job_status_queued_or_running", _test_job_status_queued_or_running
        ),
        "job_not_found": _run_case("job_not_found", _test_job_not_found),
        "stream_completed_job": _run_case("stream_completed_job", _test_stream_completed_job),
        "stream_not_found": _run_case("stream_not_found", _test_stream_not_found),
        "stream_live_progress": _run_case("stream_live_progress", _test_stream_live_progress),
        "cache_stats_endpoint": _run_case(
            "cache_stats_endpoint", _test_cache_stats_endpoint
        ),
        "metrics_empty_log": _run_case("metrics_empty_log", _test_metrics_empty_log),
        "metrics_aggregates_runs": _run_case(
            "metrics_aggregates_runs", _test_metrics_aggregates_runs
        ),
        "cache_clear_endpoint": _run_case(
            "cache_clear_endpoint", _test_cache_clear_endpoint
        ),
        # explain
        "explain_verified": _run_case("explain_verified", _test_explain_verified),
        "explain_classification_rejected": _run_case(
            "explain_classification_rejected", _test_explain_classification_rejected
        ),
        "explain_formalization_failed": _run_case(
            "explain_formalization_failed", _test_explain_formalization_failed
        ),
        # legacy
        "legacy_classify_still_works": _run_case(
            "legacy_classify_still_works", _test_legacy_classify_still_works
        ),
        # bundle 2: three-tier classifier, preamble, diagnostics
        "classify_definable_with_preamble": _run_case(
            "classify_definable_with_preamble", _test_classify_definable_with_preamble
        ),
        "formalize_with_preamble_names": _run_case(
            "formalize_with_preamble_names", _test_formalize_with_preamble_names
        ),
        "formalize_failure_with_diagnosis": _run_case(
            "formalize_failure_with_diagnosis", _test_formalize_failure_with_diagnosis
        ),
        "formalize_success_no_diagnosis": _run_case(
            "formalize_success_no_diagnosis", _test_formalize_success_no_diagnosis
        ),
        "prover_registry": _run_case("prover_registry", _test_prover_registry),
        "prover_registry_unknown": _run_case(
            "prover_registry_unknown", _test_prover_registry_unknown
        ),
    }

    print("\n" + "=" * 60)
    print("Results:")
    for name, passed in results.items():
        print(f"  {name}: {'PASS' if passed else 'FAIL'}")

    all_passed = all(results.values())
    print(f"\nOverall: {'ALL PASSED' if all_passed else 'SOME FAILED'}")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
