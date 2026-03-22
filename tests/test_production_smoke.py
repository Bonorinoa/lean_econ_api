"""Tests for scripts/production_smoke.py."""

from __future__ import annotations

import json
import sys
from subprocess import CompletedProcess
from unittest.mock import patch

import production_smoke


class _FakeResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.requests: list[tuple[str, str, dict | None]] = []
        self._job_polls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def request(self, method: str, url: str, json: dict | None = None):
        self.requests.append((method, url, json))
        if url.endswith("/health"):
            return _FakeResponse(200, {"status": "ok"})
        if url.endswith("/openapi.json"):
            return _FakeResponse(200, {"openapi": "3.1.0"})
        if url.endswith("/api/v1/metrics"):
            return _FakeResponse(200, {"total_runs": 1})
        if url.endswith("/api/v1/cache/stats"):
            return _FakeResponse(200, {"size": 0})
        if url.endswith("/api/v1/classify"):
            return _FakeResponse(200, {"category": "ALGEBRAIC"})
        if url.endswith("/api/v1/formalize"):
            return _FakeResponse(200, {"success": True})
        if url.endswith("/api/v1/verify"):
            return _FakeResponse(202, {"job_id": "job-123", "status": "queued"})
        if "/api/v1/jobs/" in url:
            self._job_polls += 1
            status = "completed" if self._job_polls >= 2 else "running"
            return _FakeResponse(200, {"job_id": "job-123", "status": status})
        raise AssertionError(f"Unexpected URL: {url}")


def test_run_smoke_collects_verify_polling(monkeypatch) -> None:
    monkeypatch.setattr(production_smoke.httpx, "Client", _FakeClient)
    monkeypatch.setattr(production_smoke.time, "sleep", lambda _: None)

    result = production_smoke.run_smoke(
        base_url="https://example.test", poll_interval=0.0, max_polls=3
    )

    assert result["health"]["status_code"] == 200
    assert result["verify"]["status_code"] == 202
    assert result["verify_polling"]["final_status"] == "completed"
    assert len(result["verify_polling"]["polls"]) == 2


def test_request_error_is_recorded(monkeypatch) -> None:
    class _TimeoutClient(_FakeClient):
        def request(self, method: str, url: str, json: dict | None = None):
            if url.endswith("/api/v1/formalize"):
                raise production_smoke.httpx.ReadTimeout("boom")
            return super().request(method, url, json=json)

    monkeypatch.setattr(production_smoke.httpx, "Client", _TimeoutClient)
    monkeypatch.setattr(production_smoke.time, "sleep", lambda _: None)

    result = production_smoke.run_smoke(
        base_url="https://example.test",
        poll_interval=0.0,
        max_polls=2,
    )

    assert result["formalize"]["ok"] is False
    assert result["formalize"]["error_type"] == "ReadTimeout"
    assert result["verify"]["status_code"] == 202


def test_request_falls_back_to_curl(monkeypatch) -> None:
    class _ConnectErrorClient(_FakeClient):
        def request(self, method: str, url: str, json: dict | None = None):
            raise production_smoke.httpx.ConnectError("dns failure")

    def fake_run(command, capture_output, text, check):
        assert command[:6] == ["curl", "-L", "--max-time", "30", "-sS", "-X"]
        assert command[6] == "GET"
        assert command[7] == "https://example.test/health"
        return CompletedProcess(command, 0, stdout='{"status":"ok"}\nHTTP_STATUS:200', stderr="")

    monkeypatch.setattr(production_smoke.httpx, "Client", _ConnectErrorClient)
    monkeypatch.setattr(production_smoke.subprocess, "run", fake_run)

    with _ConnectErrorClient() as client:
        result = production_smoke._request(
            client,
            "GET",
            "https://example.test/health",
            timeout=30.0,
        )

    assert result["status_code"] == 200
    assert result["response_body"] == {"status": "ok"}
    assert result["transport"] == "curl_fallback"


def test_main_writes_json_output(tmp_path, monkeypatch, capsys) -> None:
    output_path = tmp_path / "smoke.json"
    monkeypatch.setattr(production_smoke.httpx, "Client", _FakeClient)
    monkeypatch.setattr(production_smoke.time, "sleep", lambda _: None)

    argv = [
        "production_smoke.py",
        "--base-url",
        "https://example.test",
        "--poll-interval",
        "0",
        "--max-polls",
        "2",
        "--json-output",
        str(output_path),
    ]

    with patch.object(sys, "argv", argv):
        exit_code = production_smoke.main()

    assert exit_code == 0
    assert output_path.is_file()
    payload = json.loads(capsys.readouterr().out)
    assert payload["base_url"] == "https://example.test"
