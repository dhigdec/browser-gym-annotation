"""Session persistence — the annotator's *work* (not the trajectory).

The recorded trajectory is read-only fixture/gym data (see tasks.py). Everything
a human does on top of it — approving steps, authoring a verifier suite, running
the benchmark, submitting to the dataset — is captured here as real relational
rows so it survives a refresh and produces an auditable record.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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


def _has_nul(v: object) -> bool:
    if isinstance(v, str):
        return "\x00" in v
    if isinstance(v, dict):
        return any(_has_nul(x) for x in v.values())
    if isinstance(v, (list, tuple)):
        return any(_has_nul(x) for x in v)
    return False


class _NulSafe(BaseModel):
    """Reject NUL bytes anywhere in the request. Postgres text/json columns cannot
    store \\x00, so an unhandled NUL becomes a 500 at write time — fail closed as a
    clean 422 at the edge instead."""

    @model_validator(mode="after")
    def _reject_nul(self):
        for name, val in self.__dict__.items():
            if _has_nul(val):
                raise ValueError(f"{name} must not contain NUL bytes")
        return self


class OpenSessionBody(_NulSafe):
    # Bounded to the annotator.email column width — an over-length value must be a
    # 422, not an unhandled DB truncation 500.
    annotatorEmail: str | None = Field(default=None, max_length=255)
    fresh: bool = False  # start a NEW session instead of resuming the latest (e.g. after submit)


class PatchSessionBody(_NulSafe):
    status: str | None = None
    rerunFrom: int | None = None


class VerifierIn(_NulSafe):
    id: str = Field(max_length=64)  # bounded to verifier.ext_id column width (422, not a 500)
    level: str
    assertion: str
    code: str
    check: dict | None = None  # executable IR — persisted so the server can recompute reward
    failsUntilCorrected: bool = False
    placeholder: bool = False
    addedByHuman: bool = False


class SaveSuiteBody(_NulSafe):
    verifiers: list[VerifierIn]


class BenchmarkBody(_NulSafe):
    # `reward` is accepted for back-compat but IGNORED — the server recomputes it
    # from the persisted suite so the stored reward can never be client-asserted.
    corrected: bool = False
    overrides: list[str] = []
    reward: int | None = None
    results: dict = {}


class RunBody(_NulSafe):
    # `verifiers` is accepted for back-compat but IGNORED for scoring — the server
    # evaluates the PERSISTED suite, so a client cannot inject a passing check.
    corrected: bool = False
    verifiers: list[dict] = []
    overrides: list[str] = []


class RerunBody(_NulSafe):
    fromStep: int
    correction: str = ""
    mode: str = "deterministic"  # deterministic (oracle/gold path) | agent (live, M6b)


class SubmitBody(_NulSafe):
    reward: int
    override: bool = False
    overrideReason: str | None = None
    kind: str = "golden"


# ---- helpers ---------------------------------------------------------------


def _seed_task(db: Session, external_id: str) -> Task:
    """Ensure the given task exists as a real row (idempotent + race-safe)."""
    fx = task_fixture(external_id) or _FIXTURE
    ext = fx["task"]["id"]
    task = db.scalar(select(Task).where(Task.external_id == ext))
    if task is None:
        t = fx["task"]
        try:
            with db.begin_nested():  # SAVEPOINT — a concurrent insert won't kill the txn
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
        except IntegrityError:  # a concurrent request won the unique(external_id) — re-select it
            task = db.scalar(select(Task).where(Task.external_id == ext))
    return task


def _default_annotator(db: Session, email: str | None) -> Annotator:
    """Get-or-create the annotator, race-safe: two concurrent first-time opens for
    a brand-new email must not 500 on the unique(email) constraint."""
    email = email or _DEFAULT_ANNOTATOR
    ann = db.scalar(select(Annotator).where(Annotator.email == email))
    if ann is None:
        try:
            with db.begin_nested():  # SAVEPOINT — roll back only the failed insert, keep the txn
                ann = Annotator(email=email)
                db.add(ann)
                db.flush()
        except IntegrityError:  # a concurrent request created it first — re-select the winner
            ann = db.scalar(select(Annotator).where(Annotator.email == email))
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
    persisted = _persisted_verifiers(db, suite)
    out = evaluate(persisted, _session_fixture(db, s), corrected, overrides)
    applied_overrides = sorted(overrides & {v["id"] for v in persisted})  # the ones that actually applied
    db.add(BenchmarkRun(suite_id=suite.id, reward=out["reward"], results=out["results"], overridden=applied_overrides))
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


def _get_session(db: Session, session_id: UUID, *, lock: bool = False) -> ReviewSession:
    # lock=True takes a row lock (SELECT ... FOR UPDATE) so the mutating endpoints
    # serialize on the session row — this closes the run-vs-submit TOCTOU where a
    # /run reads a not-yet-submitted status and appends a benchmark to a session
    # /submit locks a moment later. No-op on SQLite; enforced on Postgres.
    if lock:
        s = db.scalar(select(ReviewSession).where(ReviewSession.id == session_id).with_for_update())
    else:
        s = db.get(ReviewSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session not found")
    return s


def _assert_not_submitted(s: ReviewSession) -> None:
    """A submitted session is immutable. This guard rides on EVERY mutating
    endpoint (not just PATCH/rerun/submit) so the suite and its benchmark runs
    can't be rewritten after the sample is locked — otherwise the exported
    golden bundle would drift from what was reviewed and scored."""
    if s.status == "submitted":
        raise HTTPException(
            status_code=409,
            detail="session is submitted (immutable) — start a new session to re-annotate",
        )


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
    s = _get_session(db, session_id, lock=True)
    # A submitted session is immutable — no status/correction changes via PATCH.
    if s.status == "submitted":
        raise HTTPException(status_code=409, detail="session is submitted (immutable) — start a new session to re-annotate")
    if body.status is not None:
        # 'submitted' is reachable ONLY through /submit, never by a direct status write.
        if body.status not in _OPEN:
            raise HTTPException(status_code=400, detail=f"status {body.status!r} is not a settable open state")
        if s.status != body.status:
            s.status = body.status
            _audit(db, "", "session.status", str(s.id), {"status": body.status}, session_id=s.id)
    if body.rerunFrom is not None:
        nsteps = len(_session_fixture(db, s).get("steps", []))
        if not 0 <= body.rerunFrom <= nsteps:
            raise HTTPException(status_code=422, detail=f"rerunFrom {body.rerunFrom} out of range 0..{nsteps}")
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
    s = _get_session(db, session_id, lock=True)
    if s.status == "submitted":
        raise HTTPException(status_code=409, detail="session is submitted (immutable) — start a new session to re-annotate")
    fixture = _session_fixture(db, s)
    nsteps = len(fixture.get("steps", []))
    if not 0 <= body.fromStep <= nsteps:
        raise HTTPException(status_code=422, detail=f"fromStep {body.fromStep} out of range 0..{nsteps}")
    branch_steps, actual_mode = _branch_for(body.correction, body.mode, body.fromStep, fixture)
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
    s = _get_session(db, session_id, lock=True)
    _assert_not_submitted(s)
    # Reward results are keyed by the authoring id — a duplicate id would let one
    # verifier's verdict overwrite another's, masking a failing/placeholder check.
    ids = [v.id for v in body.verifiers]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise HTTPException(status_code=422, detail=f"duplicate verifier ids: {dupes}")
    # A unique (session_id, version) means two concurrent saves can't collide on a
    # version. The violation surfaces at flush() (the INSERT), so the whole attempt
    # — recompute version, insert, commit — must sit inside the retry.
    for _attempt in range(5):
        prev = _latest_suite(db, s.id)
        version = (prev.version + 1) if prev else 1
        try:
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
            break
        except IntegrityError:
            db.rollback()  # a concurrent save took this version — recompute and retry
    else:
        raise HTTPException(status_code=409, detail="concurrent suite save — please retry")
    return _snapshot(db, s)


@router.post("/sessions/{session_id}/run")
def run_verifiers(session_id: UUID, body: RunBody, db: Session = Depends(get_db)) -> dict:
    """Execute the PERSISTED verifier suite for real against the captured DOM +
    ground-truth state + trace, record the run, and return the true per-verifier
    results. The reward is computed server-side from the stored suite — the
    client's `verifiers` are ignored for scoring, so a fabricated passing check
    cannot inflate the reward."""
    s = _get_session(db, session_id, lock=True)
    _assert_not_submitted(s)
    out = _run_benchmark(db, s, body.corrected, set(body.overrides))
    db.commit()
    return out


@router.post("/sessions/{session_id}/benchmark")
def record_benchmark(session_id: UUID, body: BenchmarkBody, db: Session = Depends(get_db)) -> dict:
    """Deprecated alias for /run — kept for back-compat. Recomputes the reward
    from the persisted suite; the client-supplied `reward` is ignored."""
    s = _get_session(db, session_id, lock=True)
    _assert_not_submitted(s)
    _run_benchmark(db, s, body.corrected, set(body.overrides))
    db.commit()
    return _snapshot(db, s)


@router.post("/sessions/{session_id}/submit")
def submit(session_id: UUID, body: SubmitBody, db: Session = Depends(get_db)) -> dict:
    """Write the dataset row. The reward stored is the AUTHORITATIVE server-computed
    reward from the latest benchmark run of the persisted suite — never the
    client-asserted `body.reward`. A benchmark must have been run first."""
    s = _get_session(db, session_id, lock=True)
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
    overridden_ids = list(last_run.overridden or [])  # verifiers a human forced to pass
    used_override = bool(overridden_ids) or body.override  # provenance is server-derived, not just the client flag
    if reward != 1 and not used_override:
        raise HTTPException(status_code=409, detail="reward != 1 requires an override")
    # A reward reached by overriding a SAFETY verifier is NOT a clean golden — the
    # provenance must ride on the sample so an unsafe run can't ship as training gold.
    suite_verifiers = db.scalars(select(Verifier).where(Verifier.suite_id == suite.id)).all()
    safety_overridden = any(v.ext_id in overridden_ids and v.level == "safety" for v in suite_verifiers)
    kind = "flagged" if safety_overridden else ("golden" if reward == 1 else "breaker")
    # Freeze the deliverable at submit time (Cluster A). export.build_sample reads
    # this snapshot, so nothing appended after the lock can rewrite the shipped
    # sample's reward or verifier suite.
    snapshot = {
        "suite_version": suite.version,
        "reward": reward,
        "results": dict(last_run.results or {}),
        "overridden": overridden_ids,
        "verifiers": [
            {"ext_id": v.ext_id, "level": v.level, "assertion": v.assertion,
             "check": v.check_ir or None, "gym_result": v.gym_result or None}
            for v in suite_verifiers
        ],
    }
    sub = Submission(
        session_id=s.id,
        reward=reward,
        kind=kind,
        submitted_with_override=used_override,
        override_reason=(body.overrideReason if used_override else None),
        snapshot=snapshot,
    )
    db.add(sub)
    s.status = "submitted"
    _audit(
        db, "", "session.submit", str(s.id),
        {
            "reward": reward, "clientAsserted": body.reward, "diverged": body.reward != reward,
            "override": used_override, "overriddenVerifiers": overridden_ids,
            "safetyOverridden": safety_overridden, "kind": kind,
        },
        session_id=s.id,
    )
    # The unique (submission.session_id) makes the check-then-insert atomic — a
    # racing concurrent submit hits the constraint and is reported as 409, not a
    # duplicate row.
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="session already submitted — start a new session to re-annotate") from None
    return _snapshot(db, s)
