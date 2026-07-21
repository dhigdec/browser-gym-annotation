"""Live gym endpoints (M6c/M8) — verify against the real world, and load real
gym tasks into the review UI (persisting the run as a full DB record, M9)."""

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agent, gym_client, gym_review, jobs, models, verify
from app.config import settings
from app.db import SessionLocal

router = APIRouter(prefix="/api/gym", tags=["gym"])


def _persist_gym_review(db: Session, task_id: str, agent: str, run: dict, review: dict) -> str:
    """Persist a real gym review as a proper FK-linked record: task (+ seed
    state) → session → trajectory (+ steps) + verifier suite (+ milestones) +
    benchmark run. Returns the session id."""
    t = run.get("trajectory") or {}
    vr = t.get("verifier_result") or {}
    seed = int(run.get("seed", 0))

    task = db.scalar(select(models.Task).where(models.Task.external_id == task_id))
    if task is None:
        task = models.Task(external_id=task_id, source="gym")
        db.add(task)
    task.source = "gym"
    task.title = review["task"]["title"]
    task.prompt = review["task"]["prompt"]
    task.category = t.get("task_category") or ""
    task.difficulty = (t.get("task_difficulty") or "").lower()
    task.priority = review["task"]["priority"]
    task.seed = seed
    task.start_url = t.get("initial_url") or ""
    task.seed_state = {"initial_url": t.get("initial_url"), "category": t.get("task_category"), "difficulty": t.get("task_difficulty")}
    task.meta = {"constraints": review["task"]["constraints"], "allowedSites": review["task"]["allowedSites"], "runSummary": review["task"]["runSummary"]}
    db.flush()

    ann = db.scalar(select(models.Annotator).where(models.Annotator.email == "annotator@deccan.ai"))
    if ann is None:
        ann = models.Annotator(email="annotator@deccan.ai")
        db.add(ann)
        db.flush()

    s = models.ReviewSession(task_id=task.id, annotator_id=ann.id, source="gym", seed=seed, agent=agent, status="benchmark_run")
    db.add(s)
    db.flush()

    traj = models.Trajectory(session_id=s.id, agent=agent, seed=seed, score=float(vr.get("score", 0.0) or 0.0), success=bool(vr.get("success")), source="gym")
    db.add(traj)
    db.flush()
    for st in review["steps"]:
        db.add(models.TrajectoryStep(trajectory_id=traj.id, idx=st["idx"], action_type=st["type"], description=st["description"], tab_id=st.get("tabId", ""), screenshot_url=st.get("image") or ""))

    suite = models.VerifierSuite(session_id=s.id, version=1)
    db.add(suite)
    db.flush()
    for v in review["verifiers"]:
        db.add(models.Verifier(suite_id=suite.id, level=v["level"], assertion=v["assertion"], code=v["code"], gym_result=v.get("gymResult", "")))
    db.add(models.BenchmarkRun(suite_id=suite.id, reward=review.get("gymReward", 0), results={v["id"]: v.get("gymResult") for v in review["verifiers"]}))
    bs = review.get("backendState") or {}
    world_summary = {
        "orders": len(bs.get("orders", []) or []),
        "cart_items": len((bs.get("cart", {}) or {}).get("items", []) or []),
        "returns": len(bs.get("returns", []) or []),
        "subscriptions": len(bs.get("subscriptions", []) or []),
        "user": bs.get("current_user_id"),
    }
    db.add(models.AuditLog(session_id=s.id, actor=ann.email, action="gym.review", target=task_id, meta={"agent": agent, "score": vr.get("score"), "success": vr.get("success"), "world": world_summary}))
    db.commit()
    return str(s.id)


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


def _run_review_job(task_id: str, agent: str, seed: int) -> dict:
    """The slow work: run a real agent on a gym task, persist it as a full DB
    record (task + seed state → session → trajectory + milestones), and return
    the review payload. Runs on a background thread (opens its own DB session)."""
    r = gym_client.run_agent(task_id, agent, seed)
    if r is None:
        raise jobs.JobFailure("gym unreachable or run failed")
    if not (r.get("trajectory") or {}).get("steps"):
        raise jobs.JobFailure("run produced no trajectory (task may lack an oracle solver)")
    review = gym_review.to_review(r, task_id, agent)
    review["backendState"] = gym_client.state()  # the REAL post-run world (cart/orders/returns/account)
    review.setdefault("gymResume", {})["worldState"] = gym_client.world()  # full multi-app world, for resume
    with SessionLocal() as db:
        try:
            review["sessionId"] = _persist_gym_review(db, task_id, agent, r, review)
            review["persisted"] = True
        except Exception as exc:  # noqa: BLE001 — the review still loads, but say so honestly
            db.rollback()
            review["persisted"] = False
            review["persistError"] = type(exc).__name__
    return review


@router.post("/tasks/{task_id:path}/run-review")
def gym_run_review(task_id: str, body: RunReviewBody) -> dict:
    """M8/M9 — enqueue a real agent run + persist as a background job; returns a
    jobId to poll. The browser-driving run is slow (up to 260s), so it runs OFF
    the request path so a proxy/read timeout can't drop a finished review."""
    job = jobs.store.submit("run-review", _run_review_job, task_id, body.agent, body.seed)
    return {"jobId": job.id, "status": job.status}


@router.get("/jobs/{job_id}")
def gym_job(job_id: str) -> dict:
    job = jobs.store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown or expired job")
    return job.public()


def _apply_edits(state: dict, edits: dict) -> dict:
    """Apply human corrections as dot-path → value edits onto a copy of the
    captured world state (e.g. {"shop.orders.ORD_1.payment_id": "pm_personal"})."""
    import copy

    out = copy.deepcopy(state)
    for path, value in (edits or {}).items():
        cur = out
        parts = path.split(".")
        for p in parts[:-1]:
            if isinstance(cur, dict):
                cur = cur.setdefault(p, {})
            else:
                cur = None
                break
        if isinstance(cur, dict):
            cur[parts[-1]] = value
    return out


class ResumeBody(BaseModel):
    taskId: str
    seed: int = 0
    worldState: dict = {}
    urlTrail: list[str] = []
    finalUrl: str = ""
    edits: dict = {}


@router.post("/resume")
def gym_resume(body: ResumeBody) -> dict:
    """Resume a gym task from a corrected mid-episode state: load the captured
    world (optionally with human edits) into the gym and replay the trajectory's
    URL trail, returning the REAL milestone verdict on the corrected world — not
    a canned tail. This is the genuine 'correct → re-verify' loop for gym tasks."""
    state = _apply_edits(body.worldState, body.edits) if body.edits else body.worldState
    verdict = gym_client.resume_verify(body.taskId, body.seed, state, body.urlTrail, body.finalUrl)
    if verdict is None:
        raise HTTPException(status_code=502, detail="gym unreachable or resume failed")
    return {
        "verdict": verdict,
        "score": verdict.get("score"),
        "success": bool(verdict.get("success")),
        "reward": 1 if verdict.get("success") else 0,
    }


def _resume_run_job(task_id: str, seed: int, state: dict, url: str, step, agent: str) -> dict:
    r = gym_client.resume_run(task_id, seed, state, url, step, agent)
    if r is None:
        raise jobs.JobFailure("gym unreachable or resume-run failed")
    if not (r.get("trajectory") or {}).get("steps"):
        raise jobs.JobFailure("resume run produced no trajectory (agent may need an API key)")
    review = gym_review.to_review(r, task_id, agent)
    review["backendState"] = gym_client.state()
    review.setdefault("gymResume", {})["worldState"] = gym_client.world()
    vr = (r.get("trajectory") or {}).get("verifier_result") or {}
    review["gymReward"] = 1 if vr.get("success") else 0  # the driven-forward verdict
    return review


class ResumeRunBody(BaseModel):
    taskId: str
    seed: int = 0
    worldState: dict = {}
    edits: dict = {}
    resumeStep: int | None = None
    resumeUrl: str = "/"
    agent: str = "llm"


def _autogen_verifiers_job(task_id: str, seed: int, iterations: int) -> dict:
    """The autonomous ORACLE LOOP (Kashyap's reward-agent design) on our stack:
    capture the INITIAL world (reset) and the GOLDEN world (oracle run), then have
    the reward agent author a verifier suite, gate it (must score 0 on initial, 1
    on golden), and iterate with feedback until it passes or the budget runs out."""
    if gym_client.reset(task_id, seed) is None:
        raise jobs.JobFailure("gym unreachable or unknown task")
    initial = gym_client.world() or {}  # full multi-app world (paths are world-rooted)
    run = gym_client.run_agent(task_id, "oracle", seed)
    if run is None:
        raise jobs.JobFailure("oracle run failed (task may lack an oracle solver)")
    golden = gym_client.world() or {}
    brief = (run.get("trajectory") or {}).get("task_brief") or task_id

    feedback: str | None = None
    history: list[dict] = []
    suite: list[dict] | None = None
    gate: dict | None = None
    for it in range(max(1, iterations)):
        suite = agent.generate_verifier_suite(brief, initial, golden, feedback)
        if not suite:
            history.append({"iteration": it + 1, "error": "reward agent produced no suite (needs API key)"})
            break
        gate = verify.evaluate_states(suite, initial, golden)
        history.append({
            "iteration": it + 1, "checks": len(suite),
            "initialReward": gate["initialReward"], "goldenReward": gate["goldenReward"],
            "oracle": gate["oracle"],
        })
        if gate["oracle"]:
            break
        fb = []
        if gate["initialReward"] != 0:
            fb.append("The suite scored 1 on the INITIAL (untouched) world but must score 0 — some check already holds before the task is done; tighten or add a check that only the golden world satisfies.")
        if gate["goldenReward"] != 1:
            fails = [k for k, r in gate["golden"]["results"].items() if r == "fail"]
            fb.append(f"The suite scored 0 on the GOLDEN (solved) world but must score 1 — these checks wrongly failed on the solved world: {fails}. Correct their paths/values.")
        feedback = " ".join(fb)
    return {
        "oracle": bool(gate and gate.get("oracle")),
        "iterations": len(history),
        "brief": brief,
        "suite": suite or [],
        "gate": gate,
        "history": history,
    }


class AutogenBody(BaseModel):
    taskId: str
    seed: int = 0
    iterations: int = 5


@router.post("/autogen-verifiers")
def gym_autogen_verifiers(body: AutogenBody) -> dict:
    """Autonomously generate + oracle-validate a verifier suite for a gym task
    (reward-agent loop: initial=0, golden=1, iterate). Slow (an oracle run + LLM
    calls) — runs as a job; poll GET /api/gym/jobs/{id}."""
    job = jobs.store.submit("autogen-verifiers", _autogen_verifiers_job, body.taskId, body.seed, body.iterations)
    return {"jobId": job.id, "status": job.status}


@router.post("/resume-run")
def gym_resume_run(body: ResumeRunBody) -> dict:
    """Drive-forward resume (async): load the corrected world (+ edits) and drive
    an OBSERVING agent FORWARD from the mid-episode URL in the gym, then verify.
    Slow + (for LLM agents) stochastic — runs as a job; poll GET /api/gym/jobs/{id}."""
    state = _apply_edits(body.worldState, body.edits) if body.edits else body.worldState
    job = jobs.store.submit(
        "resume-run", _resume_run_job, body.taskId, body.seed, state, body.resumeUrl, body.resumeStep, body.agent
    )
    return {"jobId": job.id, "status": job.status}


@router.get("/screenshot")
def gym_screenshot(path: str) -> Response:
    """Proxy a per-step screenshot PNG from the gym."""
    png = gym_client.screenshot(path)
    if png is None:
        raise HTTPException(status_code=404, detail="screenshot not found")
    return Response(content=png, media_type="image/png")
