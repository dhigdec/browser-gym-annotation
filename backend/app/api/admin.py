"""Dev-only admin utilities. Every endpoint here is HARD-GATED to the dev
environment (prod sets ENV=prod + auto_create_all=false via Alembic), so a
destructive reset can never fire against a real deployment."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import models
from app.auth import current_annotator
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])

_CONFIRM = "RESET-SESSIONS"


class ResetBody(BaseModel):
    """A destructive endpoint demands an explicit typed confirmation, so a stray or
    automated POST can never wipe a working database by accident."""

    confirm: str = ""


def _require_dev() -> None:
    # Two independent dev signals must BOTH hold: env=dev AND create_all bootstrap
    # (prod flips env=prod and auto_create_all=false). Never wipe prod data.
    if not (settings.env == "dev" and settings.auto_create_all):
        raise HTTPException(status_code=403, detail="admin endpoints are disabled outside dev")


def _require_privileged(current: models.Annotator) -> None:
    """The dev gate alone is NOT enough. A dev instance still holds real annotation
    work, and this route was reachable ANONYMOUSLY — an unauthenticated POST wiped
    58 sessions during an audit. Require a logged-in privileged identity too."""
    if current.role not in ("admin", "reviewer"):
        raise HTTPException(status_code=403, detail="admin endpoints require the admin or reviewer role")


@router.post("/reset-sessions")
def reset_sessions(
    body: ResetBody,
    current: models.Annotator = Depends(current_annotator),
    db: Session = Depends(get_db),
) -> dict:
    """Wipe all annotation SESSIONS (and their cascaded suites/verifiers/runs/
    submissions/branches/trajectories) for a clean-slate test run. Tasks and the
    catalog are preserved — only per-annotator work is cleared, so every task
    reopens fresh at 0 reviewed.

    FOUR independent gates: dev environment, authenticated caller, privileged role,
    and an explicit typed confirmation."""
    _require_dev()
    _require_privileged(current)
    if body.confirm != _CONFIRM:
        raise HTTPException(
            status_code=400,
            detail=f'destructive: this wipes all annotation work — pass {{"confirm": "{_CONFIRM}"}} to proceed',
        )
    before = db.scalar(select(func.count()).select_from(models.ReviewSession)) or 0
    annotators = db.scalar(select(func.count()).select_from(models.Annotator)) or 0
    # audit_log references sessions via ON DELETE SET NULL; clear the noise too.
    db.execute(delete(models.AuditLog))
    # Deleting sessions cascades to trajectory / verifier_suite (→verifier,
    # benchmark_run) / submission / trajectory_branch.
    db.execute(delete(models.ReviewSession))
    # Heal any per-run task fill (e.g. a prompt-edit brief that a pre-fix build
    # wrote onto the canonical row): clear gym prompts so the next original review
    # re-fills them. The task LIST reads breakers.json, so this is display-safe.
    db.execute(update(models.Task).where(models.Task.source == "gym").values(prompt=""))
    db.commit()
    return {
        "ok": True,
        "deletedSessions": int(before),
        "annotatorsKept": int(annotators),
        "tasksKept": int(db.scalar(select(func.count()).select_from(models.Task)) or 0),
    }
