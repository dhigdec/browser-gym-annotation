"""Multi-annotator QA — aggregate every annotator's submissions per task, measure
inter-annotator agreement, and let a reviewer adjudicate one as the accepted golden."""

from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

router = APIRouter(prefix="/api/qa", tags=["qa"])


def _agreement(rewards: list[int]) -> dict:
    if not rewards:
        return {"count": 0, "majorityReward": None, "agreement": None, "unanimous": True, "distribution": {}}
    c = Counter(rewards)
    top_val, top_n = c.most_common(1)[0]
    return {
        "count": len(rewards),
        "majorityReward": top_val,
        "agreement": round(top_n / len(rewards), 3),
        "unanimous": top_n == len(rewards),
        "distribution": {str(k): v for k, v in c.items()},
    }


@router.get("/tasks")
def qa_tasks(db: Session = Depends(get_db)) -> dict:
    """Every task that has ≥1 submission, with inter-annotator agreement."""
    rows = db.execute(
        select(
            models.Task.external_id, models.Task.title,
            models.Submission.reward, models.Submission.accepted,
            models.Annotator.email,
        )
        .join(models.ReviewSession, models.ReviewSession.id == models.Submission.session_id)
        .join(models.Task, models.Task.id == models.ReviewSession.task_id)
        .join(models.Annotator, models.Annotator.id == models.ReviewSession.annotator_id, isouter=True)
    ).all()

    by_task: dict[str, dict] = {}
    for ext, title, reward, accepted, email in rows:
        t = by_task.setdefault(ext, {"title": title, "rewards": [], "annotators": set(), "adjudicated": False})
        t["rewards"].append(reward)
        if email:
            t["annotators"].add(email)
        if accepted:
            t["adjudicated"] = True

    out = []
    for ext, t in by_task.items():
        ag = _agreement(t["rewards"])
        out.append({
            "taskExternalId": ext, "title": t["title"],
            "submissions": ag["count"], "annotators": len(t["annotators"]),
            "adjudicated": t["adjudicated"], "agreement": ag["agreement"],
            "majorityReward": ag["majorityReward"], "unanimous": ag["unanimous"],
            "disputed": not ag["unanimous"], "distribution": ag["distribution"],
        })
    # Surface the ones that need a reviewer first: disputed + un-adjudicated.
    out.sort(key=lambda x: (x["adjudicated"], x["unanimous"], -x["submissions"]))
    return {"tasks": out}


@router.get("/tasks/{external_id:path}/submissions")
def qa_submissions(external_id: str, db: Session = Depends(get_db)) -> dict:
    task = db.scalar(select(models.Task).where(models.Task.external_id == external_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    rows = db.execute(
        select(models.Submission, models.Annotator.email)
        .join(models.ReviewSession, models.ReviewSession.id == models.Submission.session_id)
        .join(models.Annotator, models.Annotator.id == models.ReviewSession.annotator_id, isouter=True)
        .where(models.ReviewSession.task_id == task.id)
        .order_by(models.Submission.created_at.desc())
    ).all()
    subs = [{
        "sessionId": str(sub.session_id), "submissionId": str(sub.id),
        "annotator": email or "—", "reward": sub.reward, "kind": sub.kind,
        "override": sub.submitted_with_override, "overrideReason": sub.override_reason,
        "accepted": sub.accepted, "at": sub.created_at.isoformat(),
    } for sub, email in rows]
    return {"taskExternalId": external_id, "title": task.title,
            "agreement": _agreement([s["reward"] for s in subs]), "submissions": subs}


class AdjudicateBody(BaseModel):
    sessionId: str
    reviewer: str = "reviewer@deccan.ai"
    note: str = ""


@router.post("/tasks/{external_id:path}/adjudicate")
def qa_adjudicate(external_id: str, body: AdjudicateBody, db: Session = Depends(get_db)) -> dict:
    """A reviewer accepts one annotator's submission as the golden for this task
    (clears the flag on the others)."""
    task = db.scalar(select(models.Task).where(models.Task.external_id == external_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    subs = db.scalars(
        select(models.Submission)
        .join(models.ReviewSession, models.ReviewSession.id == models.Submission.session_id)
        .where(models.ReviewSession.task_id == task.id)
    ).all()
    target = None
    for sub in subs:
        is_target = str(sub.session_id) == body.sessionId
        sub.accepted = is_target
        if is_target:
            target = sub
    if target is None:
        raise HTTPException(status_code=404, detail="no submission for that session on this task")
    db.add(models.AuditLog(
        session_id=target.session_id, actor=body.reviewer, action="qa.adjudicate",
        target=external_id, meta={"acceptedReward": target.reward, "note": body.note},
    ))
    db.commit()
    return {"accepted": str(target.session_id), "reward": target.reward}
