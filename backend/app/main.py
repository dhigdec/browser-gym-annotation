import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import models  # noqa: F401 — register ORM models on Base
from app.api.sessions import router as sessions_router
from app.api.tasks import router as tasks_router
from app.config import settings
from app.db import Base, engine

log = logging.getLogger("annotator")


def _db_ok() -> bool:
    try:
        with engine.connect() as c:
            c.execute(text("select 1"))
        return True
    except Exception:
        return False


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev bootstrap: create tables if the DB is reachable. Never hard-fail —
    # the API still serves fixtures if Postgres is down (Alembic replaces this
    # create_all in a later milestone).
    try:
        Base.metadata.create_all(engine)
        log.info("db ready — tables ensured")
    except Exception as e:  # noqa: BLE001
        log.warning("db unavailable at startup (%s) — serving fixtures only", e)
    yield


app = FastAPI(title="Browser-Use Gym Annotator API", version="0.0.1", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    ok = _db_ok()
    return {"status": "ok" if ok else "degraded", "db": "up" if ok else "down", "env": settings.env}


app.include_router(tasks_router)
app.include_router(sessions_router)
