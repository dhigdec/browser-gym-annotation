"""Live gym endpoints (M6c/M8) — verify against the real world, and load real
gym tasks into the review UI (persisting the run as a full DB record, M9)."""

import functools

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import agent, gym_client, gym_review, jobs, models, verify
from app.config import settings
from app.db import SessionLocal, get_db

router = APIRouter(prefix="/api/gym", tags=["gym"])

# The gym benchmark record (trajectory + milestones + reward) is owned by this
# system identity, kept distinct from any human annotator so it never collides
# with a person's review-progress session.
GYM_ORACLE_ANNOTATOR = "gym-oracle@system.local"


def _gym_job(fn):
    """Wrap a background gym job so an unknown-task (GymTaskNotFound, raised by the
    gym client on a 404) becomes a clean JobFailure — the SAME 'gym task not found'
    a sync endpoint returns — instead of a generic 'internal error' that leaks the
    internal /_harness route through the exception message."""
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except gym_client.GymTaskNotFound:
            raise jobs.JobFailure("gym task not found") from None
        except gym_client.GymBadRequest as e:  # surface the gym's precise diagnostic
            raise jobs.JobFailure(f"gym: {e.detail}") from None
    return inner


def _persist_gym_review(db: Session, task_id: str, agent: str, run: dict, review: dict, brief: str | None = None, persist_raw: bool = True, origin_session_id: str | None = None) -> str:
    """Persist a real gym review as a proper FK-linked record: task (+ seed
    state) → session → trajectory (+ steps) + verifier suite (+ milestones) +
    benchmark run. Returns the session id. `brief` set = this run used an annotator
    PROMPT OVERRIDE, so its brief must NOT become the canonical task prompt.
    `persist_raw=False` (drive-forward continuations) keeps the run as an
    auditable record + a scorable verdict, but WITHOUT the replayable `raw`
    payload — so it never shadows the ORIGINAL full breaking run that
    `persisted-review` reopens (the original is never overwritten or lost)."""
    t = run.get("trajectory") or {}
    vr = t.get("verifier_result") or {}
    seed = int(run.get("seed", 0))

    task = db.scalar(select(models.Task).where(models.Task.external_id == task_id))
    if task is None:
        task = models.Task(external_id=task_id, source="gym")
        db.add(task)
    task.source = "gym"
    task.title = task.title or review["task"]["title"]
    # Fill the CANONICAL prompt from an ORIGINAL run only — never from an annotator
    # brief override (even on the task's FIRST review, when task.prompt is still
    # empty), and never clobber an already-set value. A per-run prompt edit must
    # not rewrite the shared task definition every future reviewer reads.
    if not brief:
        task.prompt = task.prompt or review["task"]["prompt"]
    task.category = t.get("task_category") or ""
    task.difficulty = (t.get("task_difficulty") or "").lower()
    task.priority = review["task"]["priority"]
    task.seed = seed
    task.start_url = t.get("initial_url") or ""
    # Merge — don't clobber what capture-seed persisted (seed / current_user_id / world).
    prior = dict(task.seed_state or {})
    prior.update({"initial_url": t.get("initial_url"), "category": t.get("task_category"), "difficulty": t.get("task_difficulty")})
    task.seed_state = prior
    task.meta = {"constraints": review["task"]["constraints"], "allowedSites": review["task"]["allowedSites"], "runSummary": review["task"]["runSummary"]}
    db.flush()

    # The gym benchmark record belongs to a SYSTEM annotator, NOT the human. This
    # keeps the human's own review session (opened separately via open_session)
    # separate and FRESH — otherwise every gym run would create a benchmark_run
    # session the human then resumes as phantom-reviewed, and their real progress
    # would be lost on the next run.
    ann = db.scalar(select(models.Annotator).where(models.Annotator.email == GYM_ORACLE_ANNOTATOR))
    if ann is None:
        ann = models.Annotator(email=GYM_ORACLE_ANNOTATOR)
        db.add(ann)
        db.flush()

    origin = None
    if origin_session_id:
        from uuid import UUID as _UUID
        try:
            origin = _UUID(str(origin_session_id))
        except (ValueError, TypeError):
            origin = None
    s = models.ReviewSession(task_id=task.id, annotator_id=ann.id, source="gym", seed=seed, agent=agent,
                             status="benchmark_run", origin_session_id=origin)
    db.add(s)
    db.flush()

    # Persist the EXACT review payload (steps + screenshots + verifiers + tabs +
    # backendState + gymResume world) so reopening this task replays THIS run
    # verbatim instead of re-driving a fresh, stochastic agent. `review` already
    # carries backendState + gymResume (set by the caller) but NOT yet sessionId
    # (added after this returns) — a shallow copy keeps that out of the snapshot.
    traj = models.Trajectory(session_id=s.id, agent=agent, seed=seed, score=float(vr.get("score", 0.0) or 0.0), success=bool(vr.get("success")), source="gym", raw=(dict(review) if persist_raw else None))
    db.add(traj)
    db.flush()
    raw_steps = t.get("steps") or []  # 1:1 with review["steps"] (to_review enumerates them)
    for i, st in enumerate(review["steps"]):
        raw = raw_steps[i] if i < len(raw_steps) else {}
        db.add(models.TrajectoryStep(
            trajectory_id=traj.id, idx=st["idx"], action_type=st["type"],
            description=st["description"], tab_id=st.get("tabId", ""),
            screenshot_url=st.get("image") or "",
            url_after=st.get("url") or "",           # the step's landing URL — schema has the column
            reasoning=(raw.get("reasoning") or "").strip(),
        ))

    suite = models.VerifierSuite(session_id=s.id, version=1)
    db.add(suite)
    db.flush()
    for v in review["verifiers"]:
        # ext_id MUST equal the result-keying id (m0..mN) so benchmark_run.results
        # maps 1:1 back to each verifier row (the human save_suite path sets it too).
        db.add(models.Verifier(suite_id=suite.id, ext_id=v["id"], level=v["level"], assertion=v["assertion"], code=v["code"], gym_result=v.get("gymResult", "")))
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
    brief: str | None = None  # annotator prompt edit → re-drive the whole run under this brief


@_gym_job
def _run_review_job(task_id: str, agent: str, seed: int, brief: str | None = None) -> dict:
    """The slow work: run a real agent on a gym task, persist it as a full DB
    record (task + seed state → session → trajectory + milestones), and return
    the review payload. Runs on a background thread (opens its own DB session).
    `brief` (annotator prompt edit) re-drives the whole run under the new prompt."""
    r = gym_client.run_agent(task_id, agent, seed, brief=brief)
    if r is None:
        raise jobs.JobFailure("gym unreachable or run failed")
    if not (r.get("trajectory") or {}).get("steps"):
        raise jobs.JobFailure("run produced no trajectory (task may lack an oracle solver)")
    review = gym_review.to_review(r, task_id, agent)
    review["backendState"] = gym_client.state()  # the REAL post-run world (cart/orders/returns/account)
    review.setdefault("gymResume", {})["worldState"] = gym_client.world()  # full multi-app world, for resume
    with SessionLocal() as db:
        try:
            review["sessionId"] = _persist_gym_review(db, task_id, agent, r, review, brief=brief)
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
    job = jobs.store.submit("run-review", _run_review_job, task_id, body.agent, body.seed, body.brief)
    return {"jobId": job.id, "status": job.status}


@router.get("/tasks/{task_id:path}/persisted-review")
def gym_persisted_review(task_id: str, db: Session = Depends(get_db)) -> dict:
    """Replay the LATEST persisted gym run for a task from the DB — no live agent.
    Reopening a gym task uses this so the annotator sees the SAME run (steps,
    screenshots, verdict) they were reviewing, and a saved correction fork
    restores onto the identical trajectory. 404 (→ the client runs fresh) when the
    task was never reviewed, or its only runs predate raw-payload persistence."""
    task = db.scalar(select(models.Task).where(models.Task.external_id == task_id))
    if task is None:
        raise HTTPException(status_code=404, detail="no persisted gym review for this task")
    # The CANONICAL run: the OLDEST trajectory carrying a real replay payload — i.e.
    # the first full run-review of this breaker. Opening a breaker must ALWAYS show
    # its canonical breaking run, never something layered on top:
    #   - drive-forward continuations persist with raw=None → skipped here (a step
    #     correction forks on top, on the human session, and never replaces this);
    #   - a prompt-edit re-run is a NEWER full run shown transiently in-session, but
    #     must not become the breaker's canonical view on reopen.
    # Filtering `t.raw` in Python skips SQL NULL, legacy JSON-`null`, and empty
    # payloads across both Postgres and SQLite.
    trajs = db.scalars(
        select(models.Trajectory)
        .join(models.ReviewSession, models.Trajectory.session_id == models.ReviewSession.id)
        .where(models.ReviewSession.task_id == task.id, models.Trajectory.source == "gym")
        .order_by(models.Trajectory.created_at.asc())
        .limit(50)
    ).all()
    traj = next((t for t in trajs if t.raw), None)  # oldest real payload = the canonical breaking run
    if traj is None:
        raise HTTPException(status_code=404, detail="no persisted gym review for this task")
    review = dict(traj.raw)
    review["persisted"] = True
    review["replayed"] = True  # this payload came from the DB, not a fresh run
    return review


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


@_gym_job
def _resume_run_job(task_id: str, seed: int, state: dict, url: str, step, agent: str, origin_session_id: str | None = None) -> dict:
    r = gym_client.resume_run(task_id, seed, state, url, step, agent)
    if r is None:
        raise jobs.JobFailure("gym unreachable, task not found, or resume-run failed")
    if not (r.get("trajectory") or {}).get("steps"):
        # Name the credential for the ACTUAL agent (openai drive-forward needs the
        # OpenAI key, not Anthropic); the gym holds the keys, so default to the
        # generic reason unless the annotator's own key is the gap.
        missing = "OPENAI_API_KEY" if agent.startswith("openai") else "ANTHROPIC_API_KEY"
        reason = f"the {missing.split('_')[0].lower()} agent produced no steps (it may be rate-limited, unavailable, or missing {missing})"
        raise jobs.JobFailure(f"resume run produced no trajectory — {reason}")
    review = gym_review.to_review(r, task_id, agent)
    review["backendState"] = gym_client.state()
    review.setdefault("gymResume", {})["worldState"] = gym_client.world()
    vr = (r.get("trajectory") or {}).get("verifier_result") or {}
    review["gymReward"] = 1 if vr.get("success") else 0  # the driven-forward verdict
    # Persist the driven-forward run as a real, scorable record — but WITHOUT a
    # replayable `raw` payload, so it never shadows the ORIGINAL full breaking run
    # that persisted-review reopens. The corrected continuation itself is preserved
    # as an immutable TrajectoryBranch on the human session (rerun-gym); its verdict
    # is still picked up by _latest_gym_verdict for the corrected re-benchmark.
    with SessionLocal() as db:
        try:
            review["sessionId"] = _persist_gym_review(db, task_id, agent, r, review, persist_raw=False, origin_session_id=origin_session_id)
            review["persisted"] = True
        except Exception as exc:  # noqa: BLE001 — the review still loads
            db.rollback()
            review["persisted"] = False
            review["persistError"] = type(exc).__name__
    return review


class ResumeRunBody(BaseModel):
    taskId: str
    seed: int = 0
    worldState: dict = {}
    edits: dict = {}
    resumeStep: int | None = None
    resumeUrl: str = "/"
    agent: str = "llm"
    sessionId: str | None = None  # the HUMAN session driving the correction → verdict isolation


def _gate_policies(brief: str, golden_trace: list[dict], actions: list[dict]) -> list[dict]:
    """Propose negative-constraint policies and apply the BREAKER GATE: keep only
    those that DISCRIMINATE — the oracle trace OBEYS the policy AND a minimal
    violating counterfactual is FLAGGED VIOLATED. Returns every proposed policy
    tagged with `discriminates` (callers filter to the kept ones)."""
    out: list[dict] = []
    for i, pol in enumerate(agent.generate_trace_policies(brief, actions)):
        if agent.judge_trajectory(pol, golden_trace) is not True:  # the oracle must OBEY it
            continue
        cf = agent.generate_policy_counterfactual(pol, actions)
        discriminates = False
        if cf:
            bad_trace = golden_trace + [{"idx": len(golden_trace), "type": "action", "tabId": "gym", "description": cf}]
            discriminates = agent.judge_trajectory(pol, bad_trace) is False  # counterfactual must VIOLATE
        out.append({
            "id": f"p{i + 1}", "level": "safety", "assertion": pol,
            "code": f"policy: {pol}", "check": {"kind": "trace_policy", "policy": pol},
            "discriminates": discriminates, "counterexample": cf,
        })
    return out


@_gym_job
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
            # Be honest about WHY — the old hardcoded "(needs API key)" was wrong
            # whenever a key WAS set but the model call failed (rate limit / HTTP
            # error / non-JSON output).
            reason = (
                "no ANTHROPIC_API_KEY configured"
                if not settings.anthropic_api_key.strip()
                else "the reward-agent model call failed or returned no usable suite (it may be rate-limited or unavailable)"
            )
            history.append({"iteration": it + 1, "error": f"reward agent produced no suite — {reason}"})
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

    # NEGATIVE-CONSTRAINT policies (JP's design): propose from the brief + the
    # oracle trajectory, keep only those the CORRECT (oracle) run actually OBEYS.
    steps = (run.get("trajectory") or {}).get("steps", [])
    golden_trace = [
        {"idx": s.get("step_idx"), "type": s.get("action_kind"), "tabId": s.get("active_tab"),
         "description": s.get("reasoning") or f"{s.get('action_kind')} {s.get('action_args')}"}
        for s in steps
    ]
    actions = [{"action": s.get("action_kind"), "args": s.get("action_args")} for s in steps]
    policy_checks = _gate_policies(brief, golden_trace, actions)
    validated = [p for p in policy_checks if p["discriminates"]]
    return {
        "oracle": bool(gate and gate.get("oracle")),
        "iterations": len(history),
        "brief": brief,
        # Only gate-passing state checks + discriminating policies go in the suite.
        "suite": (suite or []) + validated,
        "stateChecks": len(suite or []),
        "policyChecks": len(validated),
        "policyProposed": len(policy_checks),
        "gate": gate,
        "history": history,
    }


def _capture_seed_world(db: Session, task_id: str, seed: int) -> dict:
    """Reset a gym task to its seed and persist the FULL initial multi-app world
    (all tab windows: shop/mail/food/calendar/market + events) into task.seed_state,
    so the task's start state lives in the DB — renderable/loadable without a live
    reset. Returns a summary."""
    reset = gym_client.reset(task_id, seed)
    if reset is None:
        raise HTTPException(status_code=502, detail="gym unreachable or unknown task")
    world = gym_client.world() or {}
    task = db.scalar(select(models.Task).where(models.Task.external_id == task_id))
    if task is None:
        task = models.Task(external_id=task_id, source="gym")
        db.add(task)
        db.flush()
    task.source = "gym"
    task.seed = seed
    task.start_url = reset.get("start_path") or task.start_url or ""
    task.seed_state = {
        "seed": seed,
        "initial_url": reset.get("start_path"),
        "category": reset.get("task_category"),
        "difficulty": reset.get("task_difficulty"),
        "current_user_id": reset.get("current_user_id"),
        "world": world,  # the full seed-0 multi-app world (all tab windows)
    }
    db.commit()
    apps = [k for k in ("shop", "mail", "food", "calendar", "market") if world.get(k) is not None]
    return {"taskId": task_id, "seed": seed, "persisted": True, "apps": apps, "startUrl": task.start_url}


class CaptureSeedBody(BaseModel):
    seed: int = 0


@router.post("/tasks/{task_id:path}/capture-seed")
def gym_capture_seed(task_id: str, body: CaptureSeedBody, db: Session = Depends(get_db)) -> dict:
    """Persist a task's full seed-0 world into the DB (task.seed_state)."""
    return _capture_seed_world(db, task_id, body.seed)


def _capture_seeds_job(limit: int | None, seed: int) -> dict:
    """Capture the full seed-0 world for many gym tasks into the DB (each committed
    independently so partial progress survives). Slow — one gym reset per task."""
    tasks = gym_client.tasks()
    if tasks is None:
        raise jobs.JobFailure("gym unreachable")
    if limit:
        tasks = tasks[:limit]
    captured, failed = 0, 0
    for tid in tasks:
        try:
            with SessionLocal() as db:
                _capture_seed_world(db, tid, seed)
            captured += 1
        except Exception:  # noqa: BLE001 — skip a task that can't be captured, keep going
            failed += 1
    return {"captured": captured, "failed": failed, "total": len(tasks)}


class CaptureSeedsBody(BaseModel):
    limit: int | None = None
    seed: int = 0


@router.post("/capture-seeds")
def gym_capture_seeds(body: CaptureSeedsBody) -> dict:
    """Bulk-capture seed-0 worlds for gym tasks into the DB (async job; poll
    GET /api/gym/jobs/{id}). Pass a limit to cap the batch."""
    job = jobs.store.submit("capture-seeds", _capture_seeds_job, body.limit, body.seed)
    return {"jobId": job.id, "status": job.status}


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
        "resume-run", _resume_run_job, body.taskId, body.seed, state, body.resumeUrl, body.resumeStep, body.agent, body.sessionId
    )
    return {"jobId": job.id, "status": job.status}


@router.get("/screenshot")
def gym_screenshot(path: str) -> Response:
    """Proxy a per-step screenshot PNG from the gym."""
    png = gym_client.screenshot(path)
    if png is None:
        raise HTTPException(status_code=404, detail="screenshot not found")
    return Response(content=png, media_type="image/png")
