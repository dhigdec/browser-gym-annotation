"""Minimal auth — login-gated platform.

Stdlib only (PBKDF2 password hashing + an HMAC-signed token in an HttpOnly
cookie). This gates the whole API behind a login and attributes work to the
signed-in user. It is deliberately small; a real deployment would add HTTPS
(Cloud Run provides it), CSRF hardening, and per-resource ownership checks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Annotator

_PBKDF2_ITERS = 200_000


# ---- passwords -------------------------------------------------------------


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt.hex()}${h.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iters, salt_hex, h_hex = stored.split("$")
        if algo != "pbkdf2":
            return False
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(h.hex(), h_hex)
    except (ValueError, TypeError):
        return False


# ---- signed token ----------------------------------------------------------


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_token(email: str) -> str:
    payload = {"sub": email, "exp": int(time.time()) + settings.auth_ttl_hours * 3600}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str | None) -> str | None:
    """Return the subject email if the token is validly signed and unexpired."""
    if not token or "." not in token:
        return None
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(settings.auth_secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "==="))
        if int(payload.get("exp", 0)) < time.time():
            return None
        return payload.get("sub")
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


# ---- cookie helpers --------------------------------------------------------


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.auth_cookie, token,
        max_age=settings.auth_ttl_hours * 3600,
        httponly=True, samesite="lax", path="/",
        secure=(settings.env != "dev"),  # HTTPS-only off localhost
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie, path="/")


# ---- dependency ------------------------------------------------------------


def _token_from(request: Request) -> str | None:
    token = request.cookies.get(settings.auth_cookie)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:]
    return token


def current_annotator(request: Request, db: Session = Depends(get_db)) -> Annotator:
    """The signed-in annotator. Gates every protected route; 401 when the token is
    missing/invalid/expired or the user no longer exists."""
    email = read_token(_token_from(request))
    if not email:
        raise HTTPException(status_code=401, detail="not authenticated")
    ann = db.scalar(select(Annotator).where(Annotator.email == email))
    if ann is None:
        raise HTTPException(status_code=401, detail="unknown user")
    return ann
