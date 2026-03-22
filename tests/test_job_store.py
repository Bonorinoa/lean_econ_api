"""Tests for job_store.py — in-memory job queue with TTL and pub/sub."""

from __future__ import annotations

import time

from job_store import JobStatus, JobStore


def test_create_and_get() -> None:
    store = JobStore()
    job_id = store.create({"claim": "test"})
    job = store.get(job_id)
    assert job is not None
    assert job["status"] == JobStatus.QUEUED
    assert job["result"] is None
    assert job["error"] is None
    assert job["request"] == {"claim": "test"}


def test_complete_sets_result() -> None:
    store = JobStore()
    job_id = store.create()
    store.complete(job_id, {"success": True, "proof": "by trivial"})
    job = store.get(job_id)
    assert job is not None
    assert job["status"] == JobStatus.COMPLETED
    assert job["result"]["success"] is True
    assert job["finished_at"] is not None


def test_fail_sets_error() -> None:
    store = JobStore()
    job_id = store.create()
    store.fail(job_id, "something broke")
    job = store.get(job_id)
    assert job is not None
    assert job["status"] == JobStatus.FAILED
    assert job["error"] == "something broke"
    assert job["finished_at"] is not None


def test_update_status() -> None:
    store = JobStore()
    job_id = store.create()
    store.update_status(job_id, JobStatus.RUNNING)
    job = store.get(job_id)
    assert job is not None
    assert job["status"] == JobStatus.RUNNING
    assert job["started_at"] is not None


def test_create_sets_queue_metadata() -> None:
    store = JobStore()
    job_id = store.create({"claim": "test"})
    job = store.get(job_id)
    assert job is not None
    assert job["queued_at"] is not None
    assert job["started_at"] is None
    assert job["finished_at"] is None
    assert job["last_progress_at"] is None
    assert job["current_stage"] is None
    assert job["stage_timings"] == {}


def test_record_progress_updates_stage_and_timestamp() -> None:
    store = JobStore()
    job_id = store.create()
    store.update_status(job_id, JobStatus.RUNNING)
    store.record_progress(job_id, "agentic_run")
    job = store.get(job_id)
    assert job is not None
    assert job["current_stage"] == "agentic_run"
    assert job["last_progress_at"] is not None


def test_record_progress_stores_elapsed_ms() -> None:
    store = JobStore()
    job_id = store.create()
    store.record_progress(job_id, "agentic_run", elapsed_ms=123.4)
    job = store.get(job_id)
    assert job is not None
    assert job["stage_timings"]["agentic_run"] == 123.4


def test_record_progress_without_elapsed_ms_leaves_timings_empty() -> None:
    store = JobStore()
    job_id = store.create()
    store.record_progress(job_id, "agentic_run")
    job = store.get(job_id)
    assert job is not None
    assert job["stage_timings"] == {}


def test_stage_timings_accumulate_multiple_stages() -> None:
    store = JobStore()
    job_id = store.create()
    store.record_progress(job_id, "parse", elapsed_ms=5.0)
    store.record_progress(job_id, "formalize", elapsed_ms=800.0)
    store.record_progress(job_id, "agentic_run", elapsed_ms=45000.0)
    job = store.get(job_id)
    assert job is not None
    assert job["stage_timings"]["parse"] == 5.0
    assert job["stage_timings"]["formalize"] == 800.0
    assert job["stage_timings"]["agentic_run"] == 45000.0


def test_done_wrapper_stage_does_not_clobber_more_specific_current_stage() -> None:
    store = JobStore()
    job_id = store.create()
    store.record_progress(job_id, "prover_dispatch", status="running")
    store.record_progress(job_id, "agentic_fast_path", status="running")
    store.record_progress(job_id, "agentic_fast_path", status="done", elapsed_ms=8.0)
    store.record_progress(job_id, "prover_dispatch", status="done", elapsed_ms=10.0)
    job = store.get(job_id)
    assert job is not None
    assert job["current_stage"] == "agentic_fast_path"
    assert job["stage_timings"]["agentic_fast_path"] == 8.0
    assert job["stage_timings"]["prover_dispatch"] == 10.0


def test_done_only_stage_sets_current_stage_when_none_exists() -> None:
    store = JobStore()
    job_id = store.create()
    store.record_progress(job_id, "cache", status="done", elapsed_ms=0.0)
    job = store.get(job_id)
    assert job is not None
    assert job["current_stage"] == "cache"
    assert job["stage_timings"]["cache"] == 0.0


def test_get_returns_none_for_missing() -> None:
    store = JobStore()
    assert store.get("nonexistent-id") is None


def test_ttl_cleanup() -> None:
    store = JobStore(ttl_seconds=0)
    job_id = store.create()
    time.sleep(0.05)
    # get() triggers cleanup
    assert store.get(job_id) is None


def test_subscribe_and_publish() -> None:
    store = JobStore()
    job_id = store.create()
    sub = store.subscribe(job_id)

    store.publish(job_id, {"type": "progress", "message": "working..."})
    event = sub.get(timeout=1.0)
    assert event["type"] == "progress"
    assert event["message"] == "working..."


def test_complete_publishes_event() -> None:
    store = JobStore()
    job_id = store.create()
    sub = store.subscribe(job_id)

    store.complete(job_id, {"success": True})
    event = sub.get(timeout=1.0)
    assert event["type"] == "complete"
    assert event["status"] == JobStatus.COMPLETED


def test_fail_publishes_event() -> None:
    store = JobStore()
    job_id = store.create()
    sub = store.subscribe(job_id)

    store.fail(job_id, "oops")
    event = sub.get(timeout=1.0)
    assert event["type"] == "complete"
    assert event["status"] == JobStatus.FAILED
    assert event["error"] == "oops"


def test_unsubscribe() -> None:
    store = JobStore()
    job_id = store.create()
    sub = store.subscribe(job_id)
    store.unsubscribe(job_id, sub)

    store.publish(job_id, {"type": "progress"})
    assert sub.empty(), "Unsubscribed queue should not receive events"
