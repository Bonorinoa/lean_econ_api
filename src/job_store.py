"""In-memory job store with TTL cleanup."""

from __future__ import annotations

import threading
import time
import uuid
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobStore:
    """Thread-safe in-memory job store."""

    def __init__(self, ttl_seconds: int = 3600):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def create(self, request_data: dict | None = None) -> str:
        job_id = str(uuid.uuid4())
        with self._lock:
            self._jobs[job_id] = {
                "status": JobStatus.QUEUED,
                "result": None,
                "error": None,
                "created_at": time.time(),
                "request": request_data,
            }
        return job_id

    def update_status(self, job_id: str, status: JobStatus) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = status

    def complete(self, job_id: str, result: dict) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = JobStatus.COMPLETED
                self._jobs[job_id]["result"] = result

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = JobStatus.FAILED
                self._jobs[job_id]["error"] = error

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            self._cleanup_expired()
            return self._jobs.get(job_id)

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [
            jid for jid, data in self._jobs.items()
            if now - data["created_at"] > self._ttl
        ]
        for jid in expired:
            del self._jobs[jid]


# Module-level singleton
job_store = JobStore()
