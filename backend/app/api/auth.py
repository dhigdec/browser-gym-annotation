"""Auth endpoints — register / login / logout / me (cookie-based).

Accounts are the seeded dummy annotators (seed.py); open self-registration is
gated OFF by settings.allow_registration, which also closes the account-claim
takeover hole. Login issues an HttpOnly signed-cookie session; every protected
route derives the annotator from that cookie (app/auth.current_annotator), never
from a client-supplied email.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import auth
from app.config import settings
from app.db import get_db
from app.models import Annotator, ReviewSession, Submission

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=200)


def _profile(ann: Annotator) -> dict:
    """The public profile shape the frontend renders (header + profile page)."""
    return {
        "id": str(ann.id),
        "email": ann.email,
        "role": ann.role,
        "displayName": ann.display_name or ann.email.split("@")[0],
        "avatarHue": ann.avatar_hue,
        "lastLoginAt": ann.last_login_at.isoformat() if ann.last_login_at else None,
    }


def _issue(response: Response, ann: Annotator) -> dict:
    auth.set_auth_cookie(response, auth.make_token(ann.email))
    return _profile(ann)


def _stats(db: Session, ann: Annotator) -> dict:
    """Live counts for the annotator's profile — computed, never stored."""
    sessions = db.scalar(select(func.count()).select_from(ReviewSession).where(ReviewSession.annotator_id == ann.id)) or 0
    rows = db.execute(
        select(Submission.kind, func.count())
        .join(ReviewSession, ReviewSession.id == Submission.session_id)
        .where(ReviewSession.annotator_id == ann.id)
        .group_by(Submission.kind)
    ).all()
    by_kind = {k: c for k, c in rows}
    return {
        "sessions": int(sessions),
        "submitted": int(sum(by_kind.values())),
        "golden": int(by_kind.get("golden", 0)),
        "breaker": int(by_kind.get("breaker", 0)),
        "flagged": int(by_kind.get("flagged", 0)),
    }


@router.post("/register")
def register(body: Credentials, response: Response, db: Session = Depends(get_db)) -> dict:
    # Open self-registration is closed by default (the 5 dummy accounts are
    # seeded). This ALSO prevents claiming a pre-existing password-less account
    # (system/legacy identities) — an account-takeover hole.
    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="registration is closed — use a provided account")
    email = body.email.strip().lower()
    if "@" not in email or "\x00" in email:
        raise HTTPException(status_code=422, detail="enter a valid email")
    if db.scalar(select(Annotator).where(Annotator.email == email)) is not None:
        raise HTTPException(status_code=409, detail="that email is already registered — log in")
    ann = Annotator(email=email, password_hash=auth.hash_password(body.password), display_name=email.split("@")[0])
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return _issue(response, ann)


@router.post("/login")
def login(body: Credentials, response: Response, db: Session = Depends(get_db)) -> dict:
    email = body.email.strip().lower()
    ann = db.scalar(select(Annotator).where(Annotator.email == email))
    if ann is None or not auth.verify_password(body.password, ann.password_hash):
        raise HTTPException(status_code=401, detail="wrong email or password")
    if not ann.is_active:
        raise HTTPException(status_code=403, detail="this account is deactivated")
    ann.last_login_at = func.now()
    db.commit()
    db.refresh(ann)
    return _issue(response, ann)


@router.post("/logout")
def logout(response: Response) -> dict:
    auth.clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(current: Annotator = Depends(auth.current_annotator), db: Session = Depends(get_db)) -> dict:
    return {**_profile(current), "stats": _stats(db, current)}
