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


def _req(method: str, path: str, body: dict | None = None, timeout: int = 20) -> dict | None:
    url = settings.gym_url.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"content-type": "application/json", "X-Harness-Token": settings.gym_harness_token},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
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


def state() -> dict | None:
    """The real post-run shop GymState (cart / orders / returns / subscriptions /
    account) read-only from GET /_harness/state — the true world the agent left."""
    return _req("GET", "/_harness/state")


def verify(step: int = 0) -> dict | None:
    return _req("POST", "/_harness/verify", {"step": step})


def run_agent(task_id: str, agent: str = "oracle", seed: int = 0) -> dict | None:
    """Trigger a full agent run in the gym (reset → drive → verify). Slow — the
    gym drives a real browser — so allow a generous timeout."""
    return _req("POST", "/_harness/run_agent", {"agent": agent, "task_id": task_id, "seed": seed}, timeout=260)


def load_state(task_id: str, seed: int, state: dict, step: int | None = None) -> dict | None:
    """Resume the gym from a corrected mid-episode world state (reset-to-seed +
    overlay). See POST /_harness/load_state."""
    body: dict = {"task_id": task_id, "seed": seed, "state": state}
    if step is not None:
        body["step"] = step
    return _req("POST", "/_harness/load_state", body)


def resume_run(task_id: str, seed: int, state: dict, url: str, step: int | None = None, agent: str = "llm") -> dict | None:
    """Drive-forward resume: load a corrected world into the gym and drive an
    OBSERVING agent forward from the mid-episode URL, then verify. Slow (a real
    agent run) + stochastic for LLM agents. See POST /_harness/resume_run."""
    body: dict = {"agent": agent, "task_id": task_id, "seed": seed, "state": state, "url": url or "/"}
    if step is not None:
        body["step"] = step
    return _req("POST", "/_harness/resume_run", body, timeout=300)


def resume_verify(task_id: str, seed: int, state: dict, url_trail: list[str], final_url: str = "") -> dict | None:
    """Load a corrected state, then replay /_harness/verify across the trajectory's
    per-step URLs so path-progression milestones fire, and return the REAL final
    milestone verdict on the resumed corrected world."""
    if load_state(task_id, seed, state) is None:
        return None
    last = None
    for i, u in enumerate(url_trail):
        last = _req("POST", "/_harness/verify", {"url": u or "/", "step": i})
    tail = final_url or (url_trail[-1] if url_trail else "/")
    final = _req("POST", "/_harness/verify", {"url": tail, "step": len(url_trail)})
    return final or last


def screenshot(path: str) -> bytes | None:
    """Fetch a per-step screenshot PNG (raw bytes) from the gym."""
    import urllib.parse
    url = settings.gym_url.rstrip("/") + "/_harness/screenshot?path=" + urllib.parse.quote(path, safe="")
    req = urllib.request.Request(url, headers={"X-Harness-Token": settings.gym_harness_token})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError):
        return None


def available() -> bool:
    return _req("GET", "/_harness/tasks") is not None
