"""Dev-only admin utilities. Every endpoint here is HARD-GATED to the dev
environment (prod sets ENV=prod + auto_create_all=false via Alembic), so a
destructive reset can never fire against a real deployment."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.db import get_db

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_dev() -> None:
    # Two independent dev signals must BOTH hold: env=dev AND create_all bootstrap
    # (prod flips env=prod and auto_create_all=false). Never wipe prod data.
    if not (settings.env == "dev" and settings.auto_create_all):
        raise HTTPException(status_code=403, detail="admin endpoints are disabled outside dev")


@router.post("/reset-sessions")
def reset_sessions(db: Session = Depends(get_db)) -> dict:
    """Wipe all annotation SESSIONS (and their cascaded suites/verifiers/runs/
    submissions/branches/trajectories) for a clean-slate test run. Tasks and the
    catalog are preserved — only per-annotator work is cleared, so every task
    reopens fresh at 0 reviewed."""
    _require_dev()
    before = db.scalar(select(func.count()).select_from(models.ReviewSession)) or 0
    annotators = db.scalar(select(func.count()).select_from(models.Annotator)) or 0
    # audit_log references sessions via ON DELETE SET NULL; clear the noise too.
    db.execute(delete(models.AuditLog))
    # Deleting sessions cascades to trajectory / verifier_suite (→verifier,
    # benchmark_run) / submission / trajectory_branch.
    db.execute(delete(models.ReviewSession))
    db.commit()
    return {
        "ok": True,
        "deletedSessions": int(before),
        "annotatorsKept": int(annotators),
        "tasksKept": int(db.scalar(select(func.count()).select_from(models.Task)) or 0),
    }
