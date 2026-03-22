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


def test_record_progress_updates_stage_and_timestamp() -> None:
    store = JobStore()
    job_id = store.create()
    store.update_status(job_id, JobStatus.RUNNING)
    store.record_progress(job_id, "agentic_run")
    job = store.get(job_id)
    assert job is not None
    assert job["current_stage"] == "agentic_run"
    assert job["last_progress_at"] is not None


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
