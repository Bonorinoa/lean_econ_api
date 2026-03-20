"""
Standalone smoke tests for the FastAPI service.

Usage:
  python tests/test_api_smoke.py
"""

from __future__ import annotations

import sys
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
    }


def _test_app_imports_and_routes() -> None:
    route_paths = {route.path for route in api.app.routes}
    assert "/health" in route_paths
    assert "/api/classify" in route_paths
    assert "/api/formalize" in route_paths
    assert "/api/verify" in route_paths


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
    response = client.post("/api/classify", json={"raw_claim": RAW_LEAN_THEOREM})
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "RAW_LEAN"
    assert body["formalizable"] is True
    assert body["is_raw_lean"] is True


def _test_classify_requires_definitions() -> None:
    client = TestClient(api.app)
    with patch.object(
        api,
        "classify_claim",
        return_value={
            "category": "REQUIRES_DEFINITIONS",
            "reason": "Needs domain-specific economic definitions.",
        },
    ):
        response = client.post(
            "/api/classify",
            json={"raw_claim": "The second welfare theorem holds under convex preferences."},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["category"] == "REQUIRES_DEFINITIONS"
    assert body["formalizable"] is False
    assert "definitions" in body["reason"].lower()


def _test_formalize_raw_lean_bypass() -> None:
    client = TestClient(api.app)
    response = client.post("/api/formalize", json={"raw_claim": RAW_LEAN_THEOREM})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["attempts"] == 0
    assert body["formalization_failed"] is False
    assert body["theorem_code"] == RAW_LEAN_THEOREM.strip()


def _test_verify_defaults_to_agentic_and_uses_preformalized() -> None:
    client = TestClient(api.app)
    captured: dict[str, str] = {}

    def fake_run_pipeline(*, raw_input: str, preformalized_theorem: str, prover_mode: str) -> dict:
        captured["raw_input"] = raw_input
        captured["preformalized_theorem"] = preformalized_theorem
        captured["prover_mode"] = prover_mode
        return _make_verify_result()

    with patch.object(api, "run_pipeline", side_effect=fake_run_pipeline):
        response = client.post("/api/verify", json={"theorem_code": RAW_LEAN_THEOREM})

    assert response.status_code == 200
    body = response.json()
    assert captured["raw_input"] == RAW_LEAN_THEOREM.strip()
    assert captured["preformalized_theorem"] == RAW_LEAN_THEOREM.strip()
    assert captured["prover_mode"] == "agentic"
    assert body["success"] is True
    assert body["prover_mode"] == "agentic"


def _test_verify_exceptions_return_500() -> None:
    client = TestClient(api.app, raise_server_exceptions=False)
    with patch.object(api, "run_pipeline", side_effect=RuntimeError("boom")):
        response = client.post("/api/verify", json={"theorem_code": RAW_LEAN_THEOREM})
    assert response.status_code == 500
    assert "Pipeline verification failed" in response.json()["detail"]


def _test_openapi_schema() -> None:
    client = TestClient(api.app)
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/api/verify" in schema["paths"]
    assert "VerifyRequest" in schema["components"]["schemas"]
    assert "VerifyResponse" in schema["components"]["schemas"]


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
        "verify_defaults_to_agentic_and_uses_preformalized": _run_case(
            "verify_defaults_to_agentic_and_uses_preformalized",
            _test_verify_defaults_to_agentic_and_uses_preformalized,
        ),
        "verify_exceptions_return_500": _run_case(
            "verify_exceptions_return_500",
            _test_verify_exceptions_return_500,
        ),
        "openapi_schema": _run_case("openapi_schema", _test_openapi_schema),
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
