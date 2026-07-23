"""Seed the task catalog (M9): the hand-authored fixture tasks + the 312 real
gym tasks, each with its seed state, so every task exists as a row from the
start. Gym seed_state is filled lazily on first review (a full run there).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth, gym_client, models
from app.api.tasks import _TASKS
from app.config import settings

# Five dummy annotator accounts to test the multi-annotator flow (login-only; open
# self-registration is off). Shared dev password below — TEST ACCOUNTS ONLY. One
# reviewer is seeded so the QA/adjudication path can be exercised.
_DEV_PASSWORD = "annotate1"  # dev-only dummy credential for the seeded test accounts
_DUMMY_ANNOTATORS = [
    ("ana@deccan.ai", "Ana Rivera", 210, "reviewer"),
    ("ben@deccan.ai", "Ben Okafor", 145, "annotator"),
    ("chloe@deccan.ai", "Chloe Tan", 335, "annotator"),
    ("diego@deccan.ai", "Diego Santos", 28, "annotator"),
    ("ela@deccan.ai", "Ela Novak", 268, "annotator"),
]


def seed_annotators(db: Session) -> int:
    """Ensure the 5 dummy test accounts exist (idempotent). Sets a password only
    if one isn't already set, so re-seeding never resets a changed password.

    NEVER runs in production: these accounts share one publicly-known dev password,
    so seeding them into a real deployment hands out working logins — one of them a
    REVIEWER, who can adjudicate which samples ship and pull the whole dataset."""
    if settings.env == "prod":
        return 0
    created = 0
    for email, name, hue, role in _DUMMY_ANNOTATORS:
        a = db.scalar(select(models.Annotator).where(models.Annotator.email == email))
        if a is None:
            a = models.Annotator(email=email)
            db.add(a)
            created += 1
        a.display_name = a.display_name or name
        a.avatar_hue = hue
        a.role = role
        a.is_active = True
        if not a.password_hash:
            a.password_hash = auth.hash_password(_DEV_PASSWORD)
    db.commit()
    return created


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
    annotators = seed_annotators(db)
    return {"fixtures": len(_TASKS), "gym_added": gym_added, "gym_reachable": ids is not None, "annotators_created": annotators}
