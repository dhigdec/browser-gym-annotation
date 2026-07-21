"""Live gym endpoints (M6c/M8) — verify against the real world, and load real
gym tasks into the review UI."""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app import gym_client, gym_review
from app.config import settings

router = APIRouter(prefix="/api/gym", tags=["gym"])


class ResetBody(BaseModel):
    taskId: str
    seed: int = 0


class VerifyBody(BaseModel):
    step: int = 0


class RunBody(BaseModel):
    taskId: str
    agent: str = "oracle"
    seed: int = 0


@router.get("/status")
def status() -> dict:
    return {"connected": gym_client.available(), "url": settings.gym_url}


@router.get("/tasks")
def gym_tasks() -> dict:
    ts = gym_client.tasks()
    if ts is None:
        raise HTTPException(status_code=502, detail="gym unreachable")
    return {"tasks": ts, "count": len(ts)}


@router.post("/reset")
def gym_reset(body: ResetBody) -> dict:
    r = gym_client.reset(body.taskId, body.seed)
    if r is None:
        raise HTTPException(status_code=502, detail="gym unreachable or unknown task")
    return {"task": r, "snapshot": gym_client.snapshot()}


@router.post("/verify")
def gym_verify(body: VerifyBody) -> dict:
    """The REAL milestone verdict for the live gym world (M6c)."""
    v = gym_client.verify(body.step)
    if v is None:
        raise HTTPException(status_code=502, detail="gym unreachable or no active episode")
    return {"snapshot": gym_client.snapshot(), "verdict": v}


@router.post("/run")
def gym_run(body: RunBody) -> dict:
    """M6c phase 2 — the full triggerable loop: run a real agent against the
    live gym, then read the true milestone verdict + world snapshot."""
    r = gym_client.run_agent(body.taskId, body.agent, body.seed)
    if r is None:
        raise HTTPException(status_code=502, detail="gym unreachable or run failed")
    return {"run": r, "verdict": gym_client.verify(0), "snapshot": gym_client.snapshot()}


class RunReviewBody(BaseModel):
    agent: str = "oracle"
    seed: int = 0


@router.post("/tasks/{task_id:path}/run-review")
def gym_run_review(task_id: str, body: RunReviewBody) -> dict:
    """M8 — run a real agent on a gym task and return a review payload (real
    brief, real steps with per-step screenshots, real milestones) for the UI."""
    r = gym_client.run_agent(task_id, body.agent, body.seed)
    if r is None:
        raise HTTPException(status_code=502, detail="gym unreachable or run failed")
    if not (r.get("trajectory") or {}).get("steps"):
        raise HTTPException(status_code=422, detail="run produced no trajectory (task may lack an oracle solver)")
    return gym_review.to_review(r, task_id, body.agent)


@router.get("/screenshot")
def gym_screenshot(path: str) -> Response:
    """Proxy a per-step screenshot PNG from the gym."""
    png = gym_client.screenshot(path)
    if png is None:
        raise HTTPException(status_code=404, detail="screenshot not found")
    return Response(content=png, media_type="image/png")
