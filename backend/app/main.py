import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import models  # noqa: F401 — register ORM models on Base
from app.auth import current_annotator
from app.api.admin import router as admin_router
from app.api.auth import router as auth_router
from app.api.export import router as export_router
from app.api.gym import router as gym_router
from app.api.qa import router as qa_router
from app.api.sessions import router as sessions_router
from app.api.tasks import router as tasks_router
from app.config import settings
from app.db import Base, engine
from app.gym_client import GymBadRequest, GymTaskNotFound

log = logging.getLogger("annotator")


def _db_ok() -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        return True
    except Exception:
        return False


_INSECURE_SECRET = "dev-insecure-auth-secret-change-me"


def _assert_prod_safe() -> None:
    """Fail CLOSED at boot in production rather than serving with forgeable
    sessions. With the shipped default secret, anyone can mint a valid token for
    any account, which makes every route gate meaningless."""
    if settings.env != "prod":
        return
    problems = []
    if settings.auth_secret == _INSECURE_SECRET or not settings.auth_secret.strip():
        problems.append("AUTH_SECRET is unset or still the shipped default (session tokens would be forgeable)")
    if settings.auto_create_all:
        problems.append("auto_create_all must be false in prod (use `alembic upgrade head`)")
    if problems:
        raise RuntimeError("refusing to start in prod: " + "; ".join(problems))


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Fail closed BEFORE serving a single request when prod is misconfigured.
    _assert_prod_safe()
    # Dev bootstrap: create tables if the DB is reachable. Never hard-fail —
    # the API still serves fixtures if Postgres is down (Alembic replaces this
    # create_all in a later milestone).
    try:
        # Dev bootstraps the schema directly; prod applies Alembic migrations
        # (alembic upgrade head) at deploy time and sets auto_create_all=false.
        if settings.auto_create_all:
            Base.metadata.create_all(engine)
        from app.db import SessionLocal
        from app.seed import seed_catalog
        with SessionLocal() as db:
            info = seed_catalog(db)
        log.info("db ready — catalog seeded %s", info)
    except Exception as e:  # noqa: BLE001
        log.warning("db bootstrap issue (%s) — serving fixtures only", e)
    yield


app = FastAPI(title="Browser-Use Gym Annotator API", version="0.0.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(GymTaskNotFound)
async def _gym_task_not_found(_: Request, exc: GymTaskNotFound) -> JSONResponse:
    # Distinguish "unknown gym task" (404) from an unreachable gym (502).
    return JSONResponse(status_code=404, content={"detail": "gym task not found"})


@app.exception_handler(GymBadRequest)
async def _gym_bad_request(_: Request, exc: GymBadRequest) -> JSONResponse:
    # Surface the gym's precise 4xx (e.g. 422 bad-state overlay) instead of a
    # misleading 502 "gym unreachable".
    return JSONResponse(status_code=exc.status, content={"detail": f"gym: {exc.detail}"})


@app.get("/health")
def health() -> dict:
    ok = _db_ok()
    return {"status": "ok" if ok else "degraded", "db": "up" if ok else "down", "env": settings.env}


# Authentication is enforced at the ROUTER level, not per-endpoint, so a new route
# is protected by default and cannot be forgotten. Only /health and the auth router
# (login/register) are public. Previously just sessions.py carried the dependency,
# leaving the task catalog, gym job triggers, QA data and the whole dataset export
# readable — and runnable — by anonymous callers.
_AUTHED = [Depends(current_annotator)]
app.include_router(auth_router)                              # public: login / register
app.include_router(tasks_router, dependencies=_AUTHED)
app.include_router(sessions_router, dependencies=_AUTHED)
app.include_router(gym_router, dependencies=_AUTHED)
app.include_router(qa_router, dependencies=_AUTHED)
app.include_router(export_router, dependencies=_AUTHED)
app.include_router(admin_router, dependencies=_AUTHED)
