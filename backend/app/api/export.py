"""Sample packaging / export (JP + Nav's deliverable).

The platform's product is not the broken run — it's the GOLDEN sample: a broken
agent run driven to a passing end-state. This module assembles a completed
annotation into the deliverable bundle — the evaluation triplet (initial setup +
seeded data + golden environment) plus the golden trajectory, the verifier suite,
and the reward — and exports it as JSON per sample or JSONL for the whole dataset.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

router = APIRouter(prefix="/api/export", tags=["export"])


def _latest(db: Session, model, session_id: UUID, order):
    return db.scalar(select(model).where(model.session_id == session_id).order_by(order))


def _steps_of(traj: models.Trajectory | None) -> list[dict]:
    if traj is None:
        return []
    return [{
        "idx": s.idx, "type": s.action_type, "description": s.description,
        "tab": s.tab_id, "screenshot": s.screenshot_url or None,
    } for s in sorted(traj.steps, key=lambda x: x.idx)]


def build_sample(db: Session, s: models.ReviewSession) -> dict:
    """Assemble the deliverable bundle for one annotation session."""
    task = db.get(models.Task, s.task_id)
    annotator = db.get(models.Annotator, s.annotator_id) if s.annotator_id else None
    traj = _latest(db, models.Trajectory, s.id, models.Trajectory.created_at.desc())
    branch = _latest(db, models.TrajectoryBranch, s.id, models.TrajectoryBranch.created_at.desc())
    suite = _latest(db, models.VerifierSuite, s.id, models.VerifierSuite.version.desc())
    run = None
    if suite:
        run = db.scalar(
            select(models.BenchmarkRun).where(models.BenchmarkRun.suite_id == suite.id).order_by(models.BenchmarkRun.created_at.desc())
        )
    sub = _latest(db, models.Submission, s.id, models.Submission.created_at.desc())

    recorded = _steps_of(traj)
    # Golden = the recorded steps up to the correction point + the corrected tail.
    # No correction (the run was already passing) ⇒ the recorded run is golden.
    if branch is not None:
        head = [st for st in recorded if st["idx"] <= branch.from_step]
        tail = (branch.steps or {}).get("steps", [])
        golden = head + [{"idx": branch.from_step + 1 + i, "type": t.get("type"), "description": t.get("description"), "tab": t.get("tabId")} for i, t in enumerate(tail)]
        correction = {"from_step": branch.from_step, "text": branch.correction, "mode": branch.mode}
    else:
        golden = recorded
        correction = None

    seed_state = (task.seed_state or {}) if task else {}
    verifiers = []
    if suite:
        for v in db.scalars(select(models.Verifier).where(models.Verifier.suite_id == suite.id)):
            verifiers.append({
                "level": v.level, "assertion": v.assertion,
                "check": v.check_ir or None, "gym_result": v.gym_result or None,
            })
    reward = run.reward if run else (sub.reward if sub else None)

    return {
        "sample_id": str(s.id),
        "task": {
            "id": task.external_id if task else None,
            "prompt": task.prompt if task else "",
            "category": task.category if task else "",
            "difficulty": task.difficulty if task else "",
            "constraints": (task.meta or {}).get("constraints", []) if task else [],
            "allowed_sites": (task.meta or {}).get("allowedSites", []) if task else [],
            "seed": task.seed if task else 0,
        },
        # The evaluation triplet: initial setup + seeded data (the seed-0 world).
        "initial_state": seed_state.get("world") or {k: v for k, v in seed_state.items() if k != "world"},
        "recorded_trajectory": recorded,          # the run under review (often the broken one)
        "correction": correction,                 # the human fix, if any
        "golden_trajectory": golden,              # the SFT trajectory — reaches a passing end-state
        "verifiers": verifiers,                   # the verifier suite that scores it
        "reward": reward,
        "submission": None if sub is None else {
            "reward": sub.reward, "kind": sub.kind, "accepted": sub.accepted,
            "override": sub.submitted_with_override, "at": sub.created_at.isoformat(),
        },
        "annotator": annotator.email if annotator else None,
        "metadata": {"source": s.source, "agent": s.agent or None, "status": s.status, "created_at": s.created_at.isoformat()},
    }


def _submitted_sessions(db: Session, accepted_only: bool):
    q = (
        select(models.ReviewSession)
        .join(models.Submission, models.Submission.session_id == models.ReviewSession.id)
        .order_by(models.ReviewSession.created_at.desc())
    )
    if accepted_only:
        q = q.where(models.Submission.accepted.is_(True))
    # distinct sessions (a session has at most one submission after the lock)
    seen, out = set(), []
    for s in db.scalars(q):
        if s.id not in seen:
            seen.add(s.id)
            out.append(s)
    return out


@router.get("/samples")
def list_samples(accepted: bool = False, db: Session = Depends(get_db)) -> dict:
    """Exportable golden samples (submitted; `accepted=true` = adjudicator-accepted)."""
    rows = []
    for s in _submitted_sessions(db, accepted):
        task = db.get(models.Task, s.task_id)
        sub = _latest(db, models.Submission, s.id, models.Submission.created_at.desc())
        rows.append({
            "sampleId": str(s.id), "taskId": task.external_id if task else None,
            "reward": sub.reward if sub else None, "kind": sub.kind if sub else None,
            "accepted": sub.accepted if sub else False, "source": s.source,
        })
    return {"count": len(rows), "samples": rows}


@router.get("/samples/{session_id}")
def export_sample(session_id: UUID, db: Session = Depends(get_db)) -> dict:
    s = db.get(models.ReviewSession, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="sample (session) not found")
    return build_sample(db, s)


@router.get("/dataset.jsonl")
def export_dataset(accepted: bool = False, db: Session = Depends(get_db)) -> Response:
    """The whole golden dataset as JSONL — one deliverable sample bundle per line."""
    import json

    lines = [json.dumps(build_sample(db, s), default=str) for s in _submitted_sessions(db, accepted)]
    body = "\n".join(lines) + ("\n" if lines else "")
    return Response(
        content=body, media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="golden_samples.jsonl"'},
    )
