"""In-process job registry for slow work (the gym browser run) that must run OFF
the HTTP request path. Thread-safe, dependency-free. The annotator runs a single
uvicorn worker, so one process owns all jobs; jobs are ephemeral (GC'd after a
TTL) — a persistent queue would be over-engineering for this workload."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

JobStatus = Literal["queued", "running", "done", "error"]


class JobFailure(Exception):
    """An EXPECTED worker failure — maps to status='error' with this message."""


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus = "queued"
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def public(self) -> dict:
        out: dict = {"jobId": self.id, "status": self.status}
        if self.status == "done":
            out["review"] = self.result
        if self.status == "error":
            out["error"] = self.error
        return out


class JobStore:
    def __init__(self, ttl_seconds: float = 3600.0):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._ttl = ttl_seconds

    def _gc(self) -> None:  # caller holds the lock
        cutoff = time.time() - self._ttl
        for jid in [j.id for j in self._jobs.values() if j.status in ("done", "error") and j.updated_at < cutoff]:
            self._jobs.pop(jid, None)

    def get(self, jid: str) -> Job | None:
        with self._lock:
            return self._jobs.get(jid)

    def _set(self, jid: str, **kw) -> None:
        with self._lock:
            j = self._jobs.get(jid)
            if j is None:
                return
            for k, v in kw.items():
                setattr(j, k, v)
            j.updated_at = time.time()

    def submit(self, kind: str, fn: Callable[..., Any], *args, **kwargs) -> Job:
        with self._lock:
            self._gc()
            job = Job(id=uuid.uuid4().hex, kind=kind)
            self._jobs[job.id] = job

        def _run() -> None:
            self._set(job.id, status="running")
            try:
                result = fn(*args, **kwargs)
                self._set(job.id, status="done", result=result)
            except JobFailure as e:
                self._set(job.id, status="error", error=str(e))
            except Exception as e:  # noqa: BLE001
                self._set(job.id, status="error", error=f"internal error: {e}")

        threading.Thread(target=_run, name=f"job-{kind}-{job.id[:8]}", daemon=True).start()
        return job


store = JobStore()  # module-level singleton (one uvicorn worker owns all jobs)
