"""Session persistence — the annotator's *work* (not the trajectory).

The recorded trajectory is read-only fixture/gym data (see tasks.py). Everything
a human does on top of it — approving steps, authoring a verifier suite, running
the benchmark, submitting to the dataset — is captured here as real relational
rows so it survives a refresh and produces an auditable record.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent import deterministic_branch, generate_branch
from app.api.tasks import _FIXTURE, task_fixture
from app.db import get_db
from app.verify import evaluate
from app.models import (
    Annotator,
    AuditLog,
    BenchmarkRun,
    ReviewSession,
    Submission,
    Task,
    Trajectory,
    TrajectoryBranch,
    TrajectoryStep,
    Verifier,
    VerifierSuite,
)

router = APIRouter(prefix="/api", tags=["sessions"])

_DEFAULT_ANNOTATOR = "annotator@deccan.ai"
_OPEN = {"draft", "steps_approved", "verifiers_generated", "benchmark_run"}
_STATUSES = _OPEN | {"submitted"}


# ---- request bodies --------------------------------------------------------


class OpenSessionBody(BaseModel):
    annotatorEmail: str | None = None
    fresh: bool = False  # start a NEW session instead of resuming the latest (e.g. after submit)


class PatchSessionBody(BaseModel):
    status: str | None = None
    rerunFrom: int | None = None


class VerifierIn(BaseModel):
    id: str
    level: str
    assertion: str
    code: str
    check: dict | None = None  # executable IR — persisted so the server can recompute reward
    failsUntilCorrected: bool = False
    placeholder: bool = False
    addedByHuman: bool = False


class SaveSuiteBody(BaseModel):
    verifiers: list[VerifierIn]


class BenchmarkBody(BaseModel):
    # `reward` is accepted for back-compat but IGNORED — the server recomputes it
    # from the persisted suite so the stored reward can never be client-asserted.
    corrected: bool = False
    overrides: list[str] = []
    reward: int | None = None
    results: dict = {}


class RunBody(BaseModel):
    # `verifiers` is accepted for back-compat but IGNORED for scoring — the server
    # evaluates the PERSISTED suite, so a client cannot inject a passing check.
    corrected: bool = False
    verifiers: list[dict] = []
    overrides: list[str] = []


class RerunBody(BaseModel):
    fromStep: int
    correction: str = ""
    mode: str = "deterministic"  # deterministic (oracle/gold path) | agent (live, M6b)


class SubmitBody(BaseModel):
    reward: int
    override: bool = False
    overrideReason: str | None = None
    kind: str = "golden"


# ---- helpers ---------------------------------------------------------------


def _seed_task(db: Session, external_id: str) -> Task:
    """Ensure the given task exists as a real row (idempotent)."""
    fx = task_fixture(external_id) or _FIXTURE
    ext = fx["task"]["id"]
    task = db.scalar(select(Task).where(Task.external_id == ext))
    if task is None:
        t = fx["task"]
        task = Task(
            external_id=ext,
            title=t["title"],
            prompt=t["prompt"],
            category=t.get("meta", ""),
            priority=t.get("priority", "Medium"),
            meta={
                "startState": t.get("startState", {}),
                "constraints": t.get("constraints", []),
                "allowedSites": t.get("allowedSites", []),
            },
        )
        db.add(task)
        db.flush()
    return task


def _default_annotator(db: Session, email: str | None) -> Annotator:
    email = email or _DEFAULT_ANNOTATOR
    ann = db.scalar(select(Annotator).where(Annotator.email == email))
    if ann is None:
        ann = Annotator(email=email)
        db.add(ann)
        db.flush()
    return ann


def _latest_suite(db: Session, session_id: UUID) -> VerifierSuite | None:
    return db.scalar(
        select(VerifierSuite)
        .where(VerifierSuite.session_id == session_id)
        .order_by(VerifierSuite.version.desc())
    )


def _persisted_verifiers(db: Session, suite: VerifierSuite) -> list[dict]:
    """The persisted suite's verifiers, shaped for evaluate(). The reward is
    ALWAYS computed from these DB rows — never from a client-supplied list — so
    the stored dataset reward is authoritative. Results key by the stable
    authoring id (ext_id) so the frontend can map them back."""
    rows = db.scalars(select(Verifier).where(Verifier.suite_id == suite.id)).all()
    return [
        {
            "id": v.ext_id or str(v.id),
            "level": v.level,
            "assertion": v.assertion,
            "code": v.code,
            "placeholder": v.placeholder,
            "check": v.check_ir or None,
        }
        for v in rows
    ]


def _run_benchmark(db: Session, s: ReviewSession, corrected: bool, overrides: set[str]) -> dict:
    """Evaluate the PERSISTED suite for real and record the run. Single source of
    truth for both /run and /benchmark — neither trusts a client reward."""
    suite = _latest_suite(db, s.id)
    if suite is None:
        raise HTTPException(status_code=409, detail="save the verifier suite before running the benchmark")
    out = evaluate(_persisted_verifiers(db, suite), _session_fixture(db, s), corrected, overrides)
    db.add(BenchmarkRun(suite_id=suite.id, reward=out["reward"], results=out["results"]))
    if s.status in _OPEN:
        s.status = "benchmark_run"
    _audit(
        db, "", "benchmark.execute", str(s.id),
        {"reward": out["reward"], "executed": out["executed"], "overridden": out["overridden"], "corrected": corrected},
        session_id=s.id,
    )
    return out


def _audit(
    db: Session, actor: str, action: str, target: str, meta: dict | None = None, session_id: UUID | None = None
) -> None:
    db.add(AuditLog(session_id=session_id, actor=actor, action=action, target=target, meta=meta or {}))


def _record_trajectory(db: Session, s: ReviewSession, fixture: dict) -> None:
    """Record the recorded run under review as real Trajectory + step rows, so a
    normal (non-gym) session has the same auditable task→session→trajectory chain
    the gym path produces. The fixture trace is the pre-correction agent run."""
    steps = fixture.get("steps", [])
    traj = Trajectory(session_id=s.id, agent=fixture.get("task", {}).get("agent", "recorded"), seed=0, source="fixture")
    db.add(traj)
    db.flush()
    for st in steps:
        db.add(
            TrajectoryStep(
                trajectory_id=traj.id,
                idx=st.get("idx", 0),
                action_type=st.get("type", ""),
                description=st.get("description", ""),
                tab_id=st.get("tabId", ""),
                screenshot_url=st.get("image", "") or "",
            )
        )


def _snapshot(db: Session, s: ReviewSession) -> dict:
    suite = _latest_suite(db, s.id)
    suite_out = None
    if suite is not None:
        vs = db.scalars(select(Verifier).where(Verifier.suite_id == suite.id)).all()
        suite_out = {
            "suiteId": str(suite.id),
            "version": suite.version,
            "verifiers": [
                {
                    "id": str(v.id),
                    "level": v.level,
                    "assertion": v.assertion,
                    "code": v.code,
                    "failsUntilCorrected": v.fails_until_corrected,
                    "placeholder": v.placeholder,
                    "addedByHuman": v.added_by_human,
                }
                for v in vs
            ],
        }
    last_bench = None
    if suite is not None:
        br = db.scalar(
            select(BenchmarkRun)
            .where(BenchmarkRun.suite_id == suite.id)
            .order_by(BenchmarkRun.created_at.desc())
        )
        if br is not None:
            last_bench = {"reward": br.reward, "results": br.results, "at": br.created_at.isoformat()}
    sub = db.scalar(
        select(Submission)
        .where(Submission.session_id == s.id)
        .order_by(Submission.created_at.desc())
    )
    submission = None
    if sub is not None:
        submission = {
            "reward": sub.reward,
            "kind": sub.kind,
            "override": sub.submitted_with_override,
            "at": sub.created_at.isoformat(),
        }
    return {
        "sessionId": str(s.id),
        "taskExternalId": _session_fixture(db, s)["task"]["id"],
        "status": s.status,
        "rerunFrom": s.rerun_from,
        "suite": suite_out,
        "lastBenchmark": last_bench,
        "submission": submission,
    }


def _get_session(db: Session, session_id: UUID) -> ReviewSession:
    s = db.get(ReviewSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return s


_EMPTY_FIXTURE = {"task": {"prompt": ""}, "steps": [], "correctedTail": [], "finalState": {"original": {}, "corrected": {}}, "tabs": []}


def _session_fixture(db: Session, s: ReviewSession) -> dict:
    """The task fixture this session is reviewing (M7). A gym-sourced session has
    no hand-authored fixture — return an EMPTY one so backend-state checks fail
    closed, rather than silently borrowing an unrelated fixture's finalState."""
    task = db.get(Task, s.task_id)
    if task is not None:
        fx = task_fixture(task.external_id)
        if fx is not None:
            return fx
        if s.source == "gym" or task.source == "gym":
            return {**_EMPTY_FIXTURE, "task": {"prompt": task.prompt or ""}}
    return _FIXTURE


def _branch_for(correction: str, mode: str, from_step: int, fixture: dict) -> tuple[list[dict], str]:
    """The corrected continuation + the mode actually used. `agent` calls a real
    model to generate the continuation (M6b); if no key is set or the call fails,
    it falls back to the deterministic ground-truth gold path."""
    if mode == "agent":
        generated = generate_branch(fixture, from_step, correction)
        if generated:
            return generated, "agent"
    return deterministic_branch(fixture, from_step, correction), "deterministic"


# ---- endpoints -------------------------------------------------------------


@router.post("/tasks/{external_id}/sessions")
def open_session(external_id: str, body: OpenSessionBody, db: Session = Depends(get_db)) -> dict:
    """Resume the annotator's most recent session for this task, or start one.
    `fresh=true` always starts a NEW session (used to re-annotate a task whose
    latest session is already submitted)."""
    fixture = task_fixture(external_id)
    if fixture is None:
        raise HTTPException(status_code=404, detail="task not found")
    task = _seed_task(db, external_id)
    ann = _default_annotator(db, body.annotatorEmail)
    existing = None
    if not body.fresh:
        existing = db.scalar(
            select(ReviewSession)
            .where(ReviewSession.task_id == task.id, ReviewSession.annotator_id == ann.id)
            .order_by(ReviewSession.created_at.desc())
        )
    if existing is None:
        existing = ReviewSession(task_id=task.id, annotator_id=ann.id, status="draft")
        db.add(existing)
        db.flush()
        _record_trajectory(db, existing, fixture)  # the auditable task→session→trajectory chain
        _audit(db, ann.email, "session.open", str(existing.id), session_id=existing.id)
    db.commit()
    db.refresh(existing)
    return _snapshot(db, existing)


@router.get("/sessions/{session_id}")
def get_session(session_id: UUID, db: Session = Depends(get_db)) -> dict:
    return _snapshot(db, _get_session(db, session_id))


@router.patch("/sessions/{session_id}")
def patch_session(session_id: UUID, body: PatchSessionBody, db: Session = Depends(get_db)) -> dict:
    s = _get_session(db, session_id)
    if body.status is not None:
        if body.status not in _STATUSES:
            raise HTTPException(status_code=400, detail=f"bad status {body.status!r}")
        if s.status != body.status:
            s.status = body.status
            _audit(db, "", "session.status", str(s.id), {"status": body.status}, session_id=s.id)
    if body.rerunFrom is not None:
        s.rerun_from = body.rerunFrom
        _audit(db, "", "session.correct", str(s.id), {"rerunFrom": body.rerunFrom}, session_id=s.id)
    db.commit()
    db.refresh(s)
    return _snapshot(db, s)


@router.post("/sessions/{session_id}/rerun")
def rerun(session_id: UUID, body: RerunBody, db: Session = Depends(get_db)) -> dict:
    """Re-run the agent from a corrected step. Persists an IMMUTABLE branch —
    versioned via parent_id, never overwritten — capturing the human correction.
    The continuation is deterministic today; a live agent plugs in at mode='agent'."""
    s = _get_session(db, session_id)
    branch_steps, actual_mode = _branch_for(body.correction, body.mode, body.fromStep, _session_fixture(db, s))
    parent = db.scalar(
        select(TrajectoryBranch)
        .where(TrajectoryBranch.session_id == s.id)
        .order_by(TrajectoryBranch.created_at.desc())
    )
    br = TrajectoryBranch(
        session_id=s.id,
        parent_id=parent.id if parent else None,
        from_step=body.fromStep,
        correction=body.correction,
        mode=actual_mode,
        steps={"steps": branch_steps},
    )
    db.add(br)
    # Correcting re-forks the trace and re-locks the review (spec §3.25).
    s.rerun_from = body.fromStep
    s.status = "draft"
    _audit(db, "", "agent.rerun", str(s.id), {"fromStep": body.fromStep, "mode": actual_mode, "correction": body.correction[:200]}, session_id=s.id)
    db.commit()
    return {"fromStep": body.fromStep, "mode": actual_mode, "steps": branch_steps}


@router.put("/sessions/{session_id}/suite")
def save_suite(session_id: UUID, body: SaveSuiteBody, db: Session = Depends(get_db)) -> dict:
    """Persist the current verifier suite as a new immutable version."""
    s = _get_session(db, session_id)
    prev = _latest_suite(db, s.id)
    version = (prev.version + 1) if prev else 1
    suite = VerifierSuite(session_id=s.id, version=version)
    db.add(suite)
    db.flush()
    for v in body.verifiers:
        db.add(
            Verifier(
                suite_id=suite.id,
                ext_id=v.id,
                level=v.level,
                assertion=v.assertion,
                code=v.code,
                check_ir=v.check or {},  # persist the executable IR so reward is server-recomputable
                fails_until_corrected=v.failsUntilCorrected,
                placeholder=v.placeholder,
                added_by_human=v.addedByHuman,
            )
        )
    _audit(db, "", "suite.save", str(suite.id), {"version": version, "count": len(body.verifiers)}, session_id=s.id)
    db.commit()
    return _snapshot(db, s)


@router.post("/sessions/{session_id}/run")
def run_verifiers(session_id: UUID, body: RunBody, db: Session = Depends(get_db)) -> dict:
    """Execute the PERSISTED verifier suite for real against the captured DOM +
    ground-truth state + trace, record the run, and return the true per-verifier
    results. The reward is computed server-side from the stored suite — the
    client's `verifiers` are ignored for scoring, so a fabricated passing check
    cannot inflate the reward."""
    s = _get_session(db, session_id)
    out = _run_benchmark(db, s, body.corrected, set(body.overrides))
    db.commit()
    return out


@router.post("/sessions/{session_id}/benchmark")
def record_benchmark(session_id: UUID, body: BenchmarkBody, db: Session = Depends(get_db)) -> dict:
    """Deprecated alias for /run — kept for back-compat. Recomputes the reward
    from the persisted suite; the client-supplied `reward` is ignored."""
    s = _get_session(db, session_id)
    _run_benchmark(db, s, body.corrected, set(body.overrides))
    db.commit()
    return _snapshot(db, s)


@router.post("/sessions/{session_id}/submit")
def submit(session_id: UUID, body: SubmitBody, db: Session = Depends(get_db)) -> dict:
    """Write the dataset row. The reward stored is the AUTHORITATIVE server-computed
    reward from the latest benchmark run of the persisted suite — never the
    client-asserted `body.reward`. A benchmark must have been run first."""
    s = _get_session(db, session_id)
    if s.status == "submitted":
        # Immutable once submitted — start a fresh session to re-annotate
        # (POST /tasks/{id}/sessions with fresh=true) rather than superseding.
        raise HTTPException(status_code=409, detail="session already submitted — start a new session to re-annotate")
    suite = _latest_suite(db, s.id)
    if suite is None:
        raise HTTPException(status_code=409, detail="no verifier suite to submit")
    last_run = db.scalar(
        select(BenchmarkRun)
        .where(BenchmarkRun.suite_id == suite.id)
        .order_by(BenchmarkRun.created_at.desc())
    )
    if last_run is None:
        raise HTTPException(status_code=409, detail="run the benchmark before submitting")
    reward = int(last_run.reward)  # authoritative — server-computed from the persisted suite
    if reward != 1 and not body.override:
        raise HTTPException(status_code=409, detail="reward != 1 requires an override")
    kind = "golden" if reward == 1 else "breaker"
    sub = Submission(
        session_id=s.id,
        reward=reward,
        kind=kind,
        submitted_with_override=body.override,
        override_reason=body.overrideReason,
    )
    db.add(sub)
    s.status = "submitted"
    _audit(
        db, "", "session.submit", str(s.id),
        {
            "reward": reward,
            "clientAsserted": body.reward,
            "diverged": body.reward != reward,
            "override": body.override,
            "kind": kind,
        },
        session_id=s.id,
    )
    db.commit()
    return _snapshot(db, s)
