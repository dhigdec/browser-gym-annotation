"""Auth endpoints — register / login / logout / me (minimal, cookie-based)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import auth
from app.db import get_db
from app.models import Annotator

router = APIRouter(prefix="/api/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=200)


def _issue(response: Response, ann: Annotator) -> dict:
    auth.set_auth_cookie(response, auth.make_token(ann.email))
    return {"email": ann.email, "role": ann.role}


@router.post("/register")
def register(body: Credentials, response: Response, db: Session = Depends(get_db)) -> dict:
    email = body.email.strip().lower()
    if "@" not in email or "\x00" in email:
        raise HTTPException(status_code=422, detail="enter a valid email")
    existing = db.scalar(select(Annotator).where(Annotator.email == email))
    if existing is not None and existing.password_hash:
        raise HTTPException(status_code=409, detail="that email is already registered — log in")
    # A pre-existing password-less annotator (e.g. seeded/legacy) may be claimed;
    # otherwise create a fresh one.
    ann = existing or Annotator(email=email)
    ann.password_hash = auth.hash_password(body.password)
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
    return _issue(response, ann)


@router.post("/logout")
def logout(response: Response) -> dict:
    auth.clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me")
def me(current: Annotator = Depends(auth.current_annotator)) -> dict:
    return {"email": current.email, "role": current.role}
