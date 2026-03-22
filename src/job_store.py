"""In-memory job store with TTL cleanup."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStore:
    """Thread-safe in-memory job store."""

    def __init__(self, ttl_seconds: int = 3600):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._subscribers: dict[str, list[queue.Queue[dict[str, Any]]]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def create(self, request_data: dict | None = None) -> str:
        job_id = str(uuid.uuid4())
        queued_at = _utc_now()
        with self._lock:
            self._jobs[job_id] = {
                "status": JobStatus.QUEUED,
                "result": None,
                "error": None,
                "created_at": time.time(),
                "queued_at": queued_at,
                "started_at": None,
                "finished_at": None,
                "last_progress_at": None,
                "current_stage": None,
                "stage_timings": {},
                "request": request_data,
            }
        return job_id

    def update_status(self, job_id: str, status: JobStatus) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = status
                if status == JobStatus.RUNNING and self._jobs[job_id]["started_at"] is None:
                    self._jobs[job_id]["started_at"] = _utc_now()

    def record_progress(
        self,
        job_id: str,
        stage: str | None,
        *,
        status: str | None = None,
        elapsed_ms: float | None = None,
    ) -> None:
        with self._lock:
            if job_id not in self._jobs:
                return
            self._jobs[job_id]["last_progress_at"] = _utc_now()
            if stage and (status != "done" or self._jobs[job_id]["current_stage"] in (None, stage)):
                self._jobs[job_id]["current_stage"] = stage
            if stage and elapsed_ms is not None:
                self._jobs[job_id]["stage_timings"][stage] = elapsed_ms

    def subscribe(self, job_id: str) -> queue.Queue[dict[str, Any]]:
        """Create a bounded subscriber queue for a job's SSE events."""
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.setdefault(job_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, job_id: str, subscriber: queue.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue when a streaming client disconnects."""
        with self._lock:
            subscribers = self._subscribers.get(job_id)
            if not subscribers:
                return
            if subscriber in subscribers:
                subscribers.remove(subscriber)
            if not subscribers:
                self._subscribers.pop(job_id, None)

    def publish(self, job_id: str, event: dict[str, Any]) -> None:
        """Publish an event to all current subscribers for a job."""
        with self._lock:
            subscribers = list(self._subscribers.get(job_id, []))

        for subscriber in subscribers:
            try:
                subscriber.put_nowait(event)
            except queue.Full:
                # SSE is best-effort; slow consumers keep the latest state via polling.
                continue

    def complete(self, job_id: str, result: dict) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = JobStatus.COMPLETED
                self._jobs[job_id]["result"] = result
                if self._jobs[job_id]["started_at"] is None:
                    self._jobs[job_id]["started_at"] = _utc_now()
                self._jobs[job_id]["finished_at"] = _utc_now()
        self.publish(
            job_id,
            {
                "type": "complete",
                "status": JobStatus.COMPLETED,
            },
        )

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = JobStatus.FAILED
                self._jobs[job_id]["error"] = error
                if self._jobs[job_id]["started_at"] is None:
                    self._jobs[job_id]["started_at"] = _utc_now()
                self._jobs[job_id]["finished_at"] = _utc_now()
        self.publish(
            job_id,
            {
                "type": "complete",
                "status": JobStatus.FAILED,
                "error": error,
            },
        )

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            self._cleanup_expired()
            return self._jobs.get(job_id)

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [jid for jid, data in self._jobs.items() if now - data["created_at"] > self._ttl]
        for jid in expired:
            del self._jobs[jid]
            self._subscribers.pop(jid, None)


# Module-level singleton
job_store = JobStore()
