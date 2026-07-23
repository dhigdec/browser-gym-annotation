"""Version-graph endpoints — the annotator's view of an attempt's lineage.

Every mutating call is explicit and versioned: a fork creates a CANDIDATE, and
selecting it is a separate compare-and-swap. Nothing here advances an attempt's
head as a side effect, which is what keeps a slow agent run from resurrecting a
branch the annotator already moved past.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, versions
from app.api.sessions import _owned_session
from app.auth import current_annotator
from app.db import get_db

router = APIRouter(prefix="/api", tags=["versions"])


def _version(db: Session, attempt: models.ReviewSession, version_id: UUID) -> models.TrajectoryVersion:
    v = db.get(models.TrajectoryVersion, version_id)
    if v is None or v.attempt_id != attempt.id:
        raise HTTPException(status_code=404, detail="version not found on this attempt")
    return v


def _step(db: Session, attempt: models.ReviewSession, step_id: UUID) -> models.TrajectoryStep:
    st = db.get(models.TrajectoryStep, step_id)
    if st is None:
        raise HTTPException(status_code=404, detail="step not found")
    traj = db.get(models.Trajectory, st.trajectory_id)
    if traj is None or traj.session_id != attempt.id:
        raise HTTPException(status_code=404, detail="step not found on this attempt")
    return st


def _describe(db: Session, v: models.TrajectoryVersion, head_id: UUID | None) -> dict:
    return {
        "id": str(v.id),
        "versionNo": v.version_no,
        "parentId": str(v.parent_version_id) if v.parent_version_id else None,
        "kind": v.kind,
        "status": v.status,
        "revision": v.revision,
        "producer": v.producer,
        "forkBeforeStepId": str(v.fork_before_step_id) if v.fork_before_step_id else None,
        "forkCheckpointId": str(v.fork_checkpoint_id) if v.fork_checkpoint_id else None,
        "isHead": v.id == head_id,
        "stepCount": len(versions.flatten(db, v)),
        "createdAt": v.created_at.isoformat(),
    }


@router.get("/sessions/{session_id}/versions")
def list_versions(
    session_id: UUID, current: models.Annotator = Depends(current_annotator), db: Session = Depends(get_db)
) -> dict:
    s = _owned_session(db, session_id, current)
    rows = versions.versions_for(db, s.id)
    return {
        "attemptId": str(s.id),
        "revision": s.revision,
        "headVersionId": str(s.active_version_id) if s.active_version_id else None,
        "agentCallCount": s.agent_call_count,
        "versions": [_describe(db, v, s.active_version_id) for v in rows],
        "verdicts": versions.verdicts_for(db, s.id),
    }


@router.get("/sessions/{session_id}/versions/{version_id}/steps")
def version_steps(
    session_id: UUID, version_id: UUID,
    current: models.Annotator = Depends(current_annotator), db: Session = Depends(get_db),
) -> dict:
    """The FLATTENED step list — inherited prefix plus this version's own suffix,
    with display numbers computed here (they are not identity)."""
    s = _owned_session(db, session_id, current)
    v = _version(db, s, version_id)
    verdicts = versions.verdicts_for(db, s.id)
    steps = versions.flat_view(db, v)
    for st in steps:
        st["verdict"] = verdicts.get(st["stepId"], {}).get("verdict", "pending")
    return {"versionId": str(v.id), "versionNo": v.version_no, "steps": steps}


class ForkBody(BaseModel):
    parentVersionId: UUID
    stepId: UUID
    mode: str = "before"  # before = reject this step | after = keep it and continue
    kind: str = versions.CORRECTION
    producer: str = ""


@router.post("/sessions/{session_id}/versions/fork")
def fork(
    session_id: UUID, body: ForkBody,
    current: models.Annotator = Depends(current_annotator), db: Session = Depends(get_db),
) -> dict:
    """Branch from a step. `before` rejects it (it will NOT appear in the child);
    `after` keeps it and resumes from the state it produced."""
    s = _owned_session(db, session_id, current)
    parent = _version(db, s, body.parentVersionId)
    step = _step(db, s, body.stepId)
    if body.mode not in ("before", "after"):
        raise HTTPException(status_code=422, detail="mode must be 'before' or 'after'")
    make = versions.fork_before if body.mode == "before" else versions.continue_after
    try:
        child = make(db, parent=parent, step=step, kind=body.kind, producer=body.producer, created_by_id=current.id)
    except versions.LineageError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.add(models.AuditLog(
        session_id=s.id, actor=current.email, action="version.fork", target=str(child.id),
        meta={"parent": str(parent.id), "mode": body.mode, "step": str(step.id), "versionNo": child.version_no},
    ))
    db.commit()
    return _describe(db, child, s.active_version_id)


class SelectBody(BaseModel):
    versionId: UUID
    expectedRevision: int


@router.post("/sessions/{session_id}/versions/select")
def select_version(
    session_id: UUID, body: SelectBody,
    current: models.Annotator = Depends(current_annotator), db: Session = Depends(get_db),
) -> dict:
    """Advance the attempt HEAD. Compare-and-swap against the revision the client
    last read — a stale client gets 409 and reloads instead of clobbering."""
    s = _owned_session(db, session_id, current, lock=True)
    v = _version(db, s, body.versionId)
    try:
        rev = versions.set_head(db, s, v, expected_revision=body.expectedRevision)
    except versions.ConcurrencyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.add(models.AuditLog(session_id=s.id, actor=current.email, action="version.select", target=str(v.id), meta={"revision": rev}))
    db.commit()
    return {"headVersionId": str(v.id), "revision": rev}


class StatusBody(BaseModel):
    status: str
    expectedRevision: int


@router.post("/sessions/{session_id}/versions/{version_id}/status")
def set_version_status(
    session_id: UUID, version_id: UUID, body: StatusBody,
    current: models.Annotator = Depends(current_annotator), db: Session = Depends(get_db),
) -> dict:
    """QC decision on a candidate (§8.5). Content never changes — only status."""
    s = _owned_session(db, session_id, current)
    v = _version(db, s, version_id)
    try:
        rev = versions.set_status(db, v, body.status, expected_revision=body.expectedRevision)
    except versions.ConcurrencyError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.add(models.AuditLog(session_id=s.id, actor=current.email, action="version.status", target=str(v.id), meta={"status": body.status}))
    db.commit()
    return {"versionId": str(v.id), "status": v.status, "revision": rev}


class VerdictBody(BaseModel):
    stepId: UUID
    verdict: str
    note: str = ""


@router.post("/sessions/{session_id}/steps/verdict")
def step_verdict(
    session_id: UUID, body: VerdictBody,
    current: models.Annotator = Depends(current_annotator), db: Session = Depends(get_db),
) -> dict:
    """Verify or reject one step, keyed by its stable id so the verdict survives a
    re-fork (the old scalar `reviewed_through` could not)."""
    s = _owned_session(db, session_id, current)
    if body.verdict not in ("pending", "verified", "rejected"):
        raise HTTPException(status_code=422, detail="verdict must be pending|verified|rejected")
    step = _step(db, s, body.stepId)
    row = versions.set_verdict(
        db, attempt_id=s.id, step_id=step.id, verdict=body.verdict, note=body.note, annotator_id=current.id
    )
    db.commit()
    return {"stepId": str(step.id), "verdict": row.verdict, "note": row.note}


@router.post("/sessions/{session_id}/versions/baseline")
def ensure_baseline(
    session_id: UUID,
    current: models.Annotator = Depends(current_annotator), db: Session = Depends(get_db),
) -> dict:
    """Materialize v1 for this attempt from the canonical recorded run. Idempotent,
    so the client can call it whenever it opens a task."""
    s = _owned_session(db, session_id, current)
    base = db.scalar(
        select(models.Trajectory)
        .where(models.Trajectory.session_id == s.id)
        .order_by(models.Trajectory.created_at.asc())
    )
    if base is None:
        base = _canonical_gym_trajectory(db, s)
    if base is None:
        raise HTTPException(status_code=409, detail="this attempt has no recorded run to baseline from")
    v1 = versions.ensure_root(db, s, base)
    db.commit()
    return _describe(db, v1, s.active_version_id)


def _canonical_gym_trajectory(db: Session, s: models.ReviewSession) -> models.Trajectory | None:
    """The bound canonical run for a gym task: the oldest gym trajectory that
    carries a real replay payload. Binding it explicitly on v1
    (`base_trajectory_id`) is what stops a later re-capture from quietly becoming
    canonical (§3.10)."""
    rows = db.scalars(
        select(models.Trajectory)
        .join(models.ReviewSession, models.Trajectory.session_id == models.ReviewSession.id)
        .where(models.ReviewSession.task_id == s.task_id, models.Trajectory.source == "gym")
        .order_by(models.Trajectory.created_at.asc())
        .limit(50)
    ).all()
    return next((t for t in rows if t.raw), None)
