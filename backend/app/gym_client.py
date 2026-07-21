"""Live gym bridge (M6c).

Thin HTTP client for the running ecommerce-browser-gym harness. It lets the
annotator reset a real gym task and read the TRUE milestone verdict evaluated
against the live world state — the ground truth the fixtures only approximate.
Agent execution (Playwright) stays gym-side; this reads + verifies over HTTP.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import settings


def _req(method: str, path: str, body: dict | None = None) -> dict | None:
    url = settings.gym_url.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"content-type": "application/json", "X-Harness-Token": settings.gym_harness_token},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None


def tasks() -> list[str] | None:
    d = _req("GET", "/_harness/tasks")
    return d.get("tasks") if d else None


def reset(task_id: str, seed: int = 0) -> dict | None:
    return _req("POST", "/_harness/reset", {"task_id": task_id, "seed": seed})


def snapshot() -> dict | None:
    return _req("GET", "/_harness/snapshot")


def world() -> dict | None:
    return _req("GET", "/_harness/world")


def verify(step: int = 0) -> dict | None:
    return _req("POST", "/_harness/verify", {"step": step})


def available() -> bool:
    return _req("GET", "/_harness/tasks") is not None
