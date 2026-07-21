"""Seed the task catalog (M9): the hand-authored fixture tasks + the 312 real
gym tasks, each with its seed state, so every task exists as a row from the
start. Gym seed_state is filled lazily on first review (a full run there).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import gym_client, models
from app.api.tasks import _TASKS


def _upsert_fixture(db: Session, external_id: str, fx: dict) -> None:
    task = fx["task"]
    row = db.scalar(select(models.Task).where(models.Task.external_id == external_id))
    if row is None:
        row = models.Task(external_id=external_id)
        db.add(row)
    row.source = "fixture"
    row.title = task["title"]
    row.prompt = task["prompt"]
    row.category = task.get("meta", "")
    row.priority = task.get("priority", "Medium")
    row.start_url = task.get("startState", {}).get("url", "")
    row.seed_state = {"startState": task.get("startState", {})}
    row.meta = {
        "constraints": task.get("constraints", []),
        "allowedSites": task.get("allowedSites", []),
        "runSummary": task.get("runSummary", []),
    }


def seed_catalog(db: Session) -> dict:
    """Upsert fixture + gym tasks. Best-effort on the gym (it may be down)."""
    for ext, fx in _TASKS.items():
        _upsert_fixture(db, ext, fx)

    gym_added = 0
    ids = gym_client.tasks()
    if ids:
        existing = set(db.scalars(select(models.Task.external_id).where(models.Task.source == "gym")).all())
        for tid in ids:
            if tid in existing:
                continue
            db.add(models.Task(
                external_id=tid, source="gym",
                title=tid.split("/")[-1].replace("_", " ").strip().capitalize(),
                prompt="",  # filled with the real brief on first review
                category=tid.split("/")[0] if "/" in tid else "",
            ))
            gym_added += 1
    db.commit()
    return {"fixtures": len(_TASKS), "gym_added": gym_added, "gym_reachable": ids is not None}
