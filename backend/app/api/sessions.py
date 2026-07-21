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

from app.api.tasks import _FIXTURE
from app.db import get_db
from app.verify import evaluate
from app.models import (
    Annotator,
    AuditLog,
    BenchmarkRun,
    ReviewSession,
    Submission,
    Task,
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


class PatchSessionBody(BaseModel):
    status: str | None = None
    rerunFrom: int | None = None


class VerifierIn(BaseModel):
    id: str
    level: str
    assertion: str
    code: str
    failsUntilCorrected: bool = False
    placeholder: bool = False
    addedByHuman: bool = False


class SaveSuiteBody(BaseModel):
    verifiers: list[VerifierIn]


class BenchmarkBody(BaseModel):
    reward: int
    results: dict = {}


class RunBody(BaseModel):
    corrected: bool = False
    verifiers: list[dict] = []
    overrides: list[str] = []


class SubmitBody(BaseModel):
    reward: int
    override: bool = False
    overrideReason: str | None = None
    kind: str = "golden"


# ---- helpers ---------------------------------------------------------------


def _seed_task(db: Session) -> Task:
    """Ensure the fixture task exists as a real row (idempotent)."""
    ext = _FIXTURE["task"]["id"]
    task = db.scalar(select(Task).where(Task.external_id == ext))
    if task is None:
        t = _FIXTURE["task"]
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


def _audit(db: Session, actor: str, action: str, target: str, meta: dict | None = None) -> None:
    db.add(AuditLog(actor=actor, action=action, target=target, meta=meta or {}))


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
        "taskExternalId": _FIXTURE["task"]["id"],
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


# ---- endpoints -------------------------------------------------------------


@router.post("/tasks/{external_id}/sessions")
def open_session(external_id: str, body: OpenSessionBody, db: Session = Depends(get_db)) -> dict:
    """Resume the annotator's most recent session for this task, or start one."""
    if external_id != _FIXTURE["task"]["id"]:
        raise HTTPException(status_code=404, detail="task not found")
    task = _seed_task(db)
    ann = _default_annotator(db, body.annotatorEmail)
    existing = db.scalar(
        select(ReviewSession)
        .where(ReviewSession.task_id == task.id, ReviewSession.annotator_id == ann.id)
        .order_by(ReviewSession.created_at.desc())
    )
    if existing is None:
        existing = ReviewSession(task_id=task.id, annotator_id=ann.id, status="draft")
        db.add(existing)
        db.flush()
        _audit(db, ann.email, "session.open", str(existing.id))
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
            _audit(db, "", "session.status", str(s.id), {"status": body.status})
    if body.rerunFrom is not None:
        s.rerun_from = body.rerunFrom
        _audit(db, "", "session.correct", str(s.id), {"rerunFrom": body.rerunFrom})
    db.commit()
    db.refresh(s)
    return _snapshot(db, s)


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
                level=v.level,
                assertion=v.assertion,
                code=v.code,
                fails_until_corrected=v.failsUntilCorrected,
                placeholder=v.placeholder,
                added_by_human=v.addedByHuman,
            )
        )
    _audit(db, "", "suite.save", str(suite.id), {"version": version, "count": len(body.verifiers)})
    db.commit()
    return _snapshot(db, s)


@router.post("/sessions/{session_id}/run")
def run_verifiers(session_id: UUID, body: RunBody, db: Session = Depends(get_db)) -> dict:
    """Execute the verifier suite for real against the captured DOM + ground-truth
    state + trace, record the run, and return the true per-verifier results."""
    s = _get_session(db, session_id)
    out = evaluate(body.verifiers, _FIXTURE, body.corrected, set(body.overrides))
    suite = _latest_suite(db, s.id)
    if suite is not None:
        db.add(BenchmarkRun(suite_id=suite.id, reward=out["reward"], results=out["results"]))
    if s.status in _OPEN:
        s.status = "benchmark_run"
    _audit(
        db, "", "benchmark.execute", str(s.id),
        {"reward": out["reward"], "executed": out["executed"], "overridden": out["overridden"]},
    )
    db.commit()
    return out


@router.post("/sessions/{session_id}/benchmark")
def record_benchmark(session_id: UUID, body: BenchmarkBody, db: Session = Depends(get_db)) -> dict:
    s = _get_session(db, session_id)
    suite = _latest_suite(db, s.id)
    if suite is None:
        raise HTTPException(status_code=409, detail="no verifier suite to benchmark")
    run = BenchmarkRun(suite_id=suite.id, reward=int(body.reward), results=body.results)
    db.add(run)
    if s.status in _OPEN:
        s.status = "benchmark_run"
    _audit(db, "", "benchmark.run", str(suite.id), {"reward": body.reward})
    db.commit()
    return _snapshot(db, s)


@router.post("/sessions/{session_id}/submit")
def submit(session_id: UUID, body: SubmitBody, db: Session = Depends(get_db)) -> dict:
    s = _get_session(db, session_id)
    if body.reward != 1 and not body.override:
        raise HTTPException(status_code=409, detail="reward != 1 requires an override")
    sub = Submission(
        session_id=s.id,
        reward=int(body.reward),
        kind=body.kind,
        submitted_with_override=body.override,
        override_reason=body.overrideReason,
    )
    db.add(sub)
    s.status = "submitted"
    _audit(
        db, "", "session.submit", str(s.id),
        {"reward": body.reward, "override": body.override, "kind": body.kind},
    )
    db.commit()
    return _snapshot(db, s)
