"""Run a tiny manual smoke test against a deployed LeanEcon instance."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://leaneconapi-production.up.railway.app"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_MAX_POLLS = 20
REQUIRED_FAST_CHECKS = ("health", "openapi", "metrics", "cache_stats", "classify", "formalize")

TRIVIAL_CLAIM = "1 + 1 = 2"
TRIVIAL_THEOREM = """\
import Mathlib
open Real

theorem one_plus_one : 1 + 1 = 2 := by
  sorry
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview_payload(payload: Any, limit: int = 500) -> str:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False)
    else:
        text = str(payload)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    started_at = _utc_now()
    start = time.perf_counter()
    try:
        response = client.request(method, url, json=json_body)
    except httpx.HTTPError as exc:
        return _request_via_curl(
            method=method,
            url=url,
            json_body=json_body,
            timeout=timeout,
            started_at=started_at,
            original_error=exc,
        )

    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    ended_at = _utc_now()

    try:
        response_body: Any = response.json()
    except ValueError:
        response_body = response.text

    return {
        "method": method,
        "url": url,
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "latency_ms": latency_ms,
        "status_code": response.status_code,
        "ok": response.is_success,
        "request_json": json_body,
        "response_body": response_body,
        "response_preview": _preview_payload(response_body),
        "error_type": None,
        "error_message": None,
    }


def _request_via_curl(
    *,
    method: str,
    url: str,
    json_body: dict[str, Any] | None,
    timeout: float,
    started_at: str,
    original_error: Exception,
) -> dict[str, Any]:
    start = time.perf_counter()
    max_time = max(1, int(round(timeout)))
    command = [
        "curl",
        "-L",
        "--max-time",
        str(max_time),
        "-sS",
        "-X",
        method,
        url,
        "-w",
        "\nHTTP_STATUS:%{http_code}",
    ]
    if json_body is not None:
        command.extend(
            [
                "-H",
                "Content-Type: application/json",
                "--data",
                json.dumps(json_body, ensure_ascii=False),
            ]
        )

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    ended_at = _utc_now()

    if completed.returncode != 0:
        stderr_text = completed.stderr.strip()
        message = str(original_error)
        if stderr_text:
            message = f"{message}; curl fallback failed: {stderr_text}"
        return {
            "method": method,
            "url": url,
            "started_at_utc": started_at,
            "ended_at_utc": ended_at,
            "latency_ms": latency_ms,
            "status_code": None,
            "ok": False,
            "request_json": json_body,
            "response_body": None,
            "response_preview": None,
            "error_type": type(original_error).__name__,
            "error_message": message,
            "transport": "curl_fallback_failed",
        }

    body_text, _, status_text = completed.stdout.rpartition("\nHTTP_STATUS:")
    status_code = None
    if status_text.strip().isdigit():
        status_code = int(status_text.strip())

    body_text = body_text.strip()
    try:
        response_body: Any = json.loads(body_text) if body_text else None
    except json.JSONDecodeError:
        response_body = body_text

    return {
        "method": method,
        "url": url,
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "latency_ms": latency_ms,
        "status_code": status_code,
        "ok": bool(status_code and 200 <= status_code < 300),
        "request_json": json_body,
        "response_body": response_body,
        "response_preview": _preview_payload(response_body),
        "error_type": None,
        "error_message": None,
        "transport": "curl_fallback",
    }


def _poll_job(
    client: httpx.Client,
    base_url: str,
    job_id: str,
    *,
    poll_interval: float,
    max_polls: int,
) -> dict[str, Any]:
    poll_records: list[dict[str, Any]] = []
    final_status = "timed_out"

    for _ in range(max_polls):
        record = _request(client, "GET", f"{base_url}/api/v1/jobs/{job_id}")
        poll_records.append(record)
        if record["error_type"]:
            final_status = "request_error"
            break

        body = record["response_body"] if isinstance(record["response_body"], dict) else {}
        final_status = str(body.get("status") or "unknown")
        if final_status in {"completed", "failed"}:
            break
        time.sleep(poll_interval)

    if final_status not in {"completed", "failed"}:
        record = _request(client, "GET", f"{base_url}/api/v1/jobs/{job_id}")
        poll_records.append(record)
        if record["error_type"]:
            final_status = "request_error"
        else:
            body = record["response_body"] if isinstance(record["response_body"], dict) else {}
            final_status = str(body.get("status") or "unknown")

    return {
        "job_id": job_id,
        "final_status": final_status,
        "polls": poll_records,
    }


def _timestamp_delta_seconds(started_at: Any, ended_at: Any) -> float | None:
    if not isinstance(started_at, str) or not isinstance(ended_at, str):
        return None
    try:
        started = datetime.fromisoformat(started_at)
        ended = datetime.fromisoformat(ended_at)
    except ValueError:
        return None
    return round((ended - started).total_seconds(), 3)


def _build_release_summary(records: dict[str, Any]) -> dict[str, Any]:
    required_checks_ok = all(
        isinstance(records.get(check_name), dict) and bool(records[check_name].get("ok"))
        for check_name in REQUIRED_FAST_CHECKS
    )

    verify_record = records.get("verify")
    verify_polling = records.get("verify_polling")
    verify_status_ok = isinstance(verify_record, dict) and verify_record.get("status_code") == 202

    verify_completed = False
    verify_success = False
    verify_result_partial = None
    verify_final_status = None
    verify_final_stage = None
    verify_queue_to_finish_seconds = None
    verify_elapsed_seconds = None

    final_poll_body: dict[str, Any] = {}
    if isinstance(verify_polling, dict):
        verify_final_status = verify_polling.get("final_status")
        verify_completed = verify_final_status == "completed"
        polls = verify_polling.get("polls") or []
        if polls:
            last_poll = polls[-1]
            if isinstance(last_poll, dict) and isinstance(last_poll.get("response_body"), dict):
                final_poll_body = last_poll["response_body"]

    result_payload = final_poll_body.get("result")
    result_body = result_payload if isinstance(result_payload, dict) else {}
    verify_success = verify_completed and bool(result_body.get("success"))
    if verify_completed:
        verify_result_partial = bool(result_body.get("partial", False))
    verify_final_stage = final_poll_body.get("current_stage")
    verify_queue_to_finish_seconds = _timestamp_delta_seconds(
        final_poll_body.get("queued_at"),
        final_poll_body.get("finished_at"),
    )
    if isinstance(result_body.get("elapsed_seconds"), (int, float)):
        verify_elapsed_seconds = float(result_body["elapsed_seconds"])

    overall_ok = required_checks_ok and verify_status_ok and verify_success

    return {
        "required_checks_ok": required_checks_ok,
        "verify_accepted": verify_status_ok,
        "verify_completed": verify_completed,
        "verify_success": verify_success,
        "verify_final_status": verify_final_status,
        "verify_final_stage": verify_final_stage,
        "verify_result_partial": verify_result_partial,
        "verify_queue_to_finish_seconds": verify_queue_to_finish_seconds,
        "verify_elapsed_seconds": verify_elapsed_seconds,
        "overall_ok": overall_ok,
    }


def run_smoke(
    *,
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    max_polls: int = DEFAULT_MAX_POLLS,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    records: dict[str, Any] = {
        "base_url": base_url,
        "started_at_utc": _utc_now(),
    }

    with httpx.Client(timeout=timeout, follow_redirects=True, trust_env=False) as client:
        records["health"] = _request(client, "GET", f"{base_url}/health", timeout=timeout)
        records["openapi"] = _request(client, "GET", f"{base_url}/openapi.json", timeout=timeout)
        records["metrics"] = _request(client, "GET", f"{base_url}/api/v1/metrics", timeout=timeout)
        records["cache_stats"] = _request(
            client,
            "GET",
            f"{base_url}/api/v1/cache/stats",
            timeout=timeout,
        )
        records["classify"] = _request(
            client,
            "POST",
            f"{base_url}/api/v1/classify",
            json_body={"raw_claim": TRIVIAL_CLAIM},
            timeout=timeout,
        )
        records["formalize"] = _request(
            client,
            "POST",
            f"{base_url}/api/v1/formalize",
            json_body={"raw_claim": TRIVIAL_CLAIM},
            timeout=timeout,
        )

        verify_record = _request(
            client,
            "POST",
            f"{base_url}/api/v1/verify",
            json_body={"theorem_code": TRIVIAL_THEOREM, "explain": False},
            timeout=timeout,
        )
        records["verify"] = verify_record

        verify_body = verify_record["response_body"]
        if isinstance(verify_body, dict) and verify_record["status_code"] == 202:
            job_id = verify_body.get("job_id")
            if job_id:
                records["verify_polling"] = _poll_job(
                    client,
                    base_url,
                    str(job_id),
                    poll_interval=poll_interval,
                    max_polls=max_polls,
                )

    records["summary"] = _build_release_summary(records)
    records["ended_at_utc"] = _utc_now()
    return records


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual smoke test for a deployed LeanEcon API.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS)
    parser.add_argument("--max-polls", type=int, default=DEFAULT_MAX_POLLS)
    parser.add_argument("--json-output", default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_smoke(
        base_url=args.base_url,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        max_polls=args.max_polls,
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    print(rendered)

    if args.json_output:
        output_path = Path(args.json_output).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")

    return 0 if result.get("summary", {}).get("overall_ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
