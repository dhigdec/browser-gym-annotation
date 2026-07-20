"""Core platform schema (Postgres). Operational data only — the gym's world
state stays in-memory in the gym process. Enums kept as short strings for now;
tighten to native enums with the first Alembic migration.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, ForeignKey, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


class Annotator(Base):
    __tablename__ = "annotator"
    id: Mapped[UUID] = _pk()
    email: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(32), default="annotator")  # annotator | reviewer | admin
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class Task(Base):
    __tablename__ = "task"
    id: Mapped[UUID] = _pk()
    external_id: Mapped[str] = mapped_column(String(64), index=True)  # e.g. "GYM-2041"
    title: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(64), default="")
    priority: Mapped[str] = mapped_column(String(16), default="Medium")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # constraints, allowed sites, start state
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class ReviewSession(Base):
    __tablename__ = "review_session"
    id: Mapped[UUID] = _pk()
    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id"))
    annotator_id: Mapped[UUID | None] = mapped_column(ForeignKey("annotator.id"), nullable=True)
    # draft | steps_approved | verifiers_generated | benchmark_run | submitted
    status: Mapped[str] = mapped_column(String(32), default="draft")
    rerun_from: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    suites: Mapped[list["VerifierSuite"]] = relationship(back_populates="session")


class VerifierSuite(Base):
    __tablename__ = "verifier_suite"
    id: Mapped[UUID] = _pk()
    session_id: Mapped[UUID] = mapped_column(ForeignKey("review_session.id"))
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    session: Mapped[ReviewSession] = relationship(back_populates="suites")
    verifiers: Mapped[list["Verifier"]] = relationship(back_populates="suite")


class Verifier(Base):
    __tablename__ = "verifier"
    id: Mapped[UUID] = _pk()
    suite_id: Mapped[UUID] = mapped_column(ForeignKey("verifier_suite.id"))
    level: Mapped[str] = mapped_column(String(16))  # ui | backend | semantic | process | safety
    assertion: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    fails_until_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by_human: Mapped[bool] = mapped_column(Boolean, default=False)

    suite: Mapped[VerifierSuite] = relationship(back_populates="verifiers")


class BenchmarkRun(Base):
    __tablename__ = "benchmark_run"
    id: Mapped[UUID] = _pk()
    suite_id: Mapped[UUID] = mapped_column(ForeignKey("verifier_suite.id"))
    reward: Mapped[int] = mapped_column(default=0)
    results: Mapped[dict] = mapped_column(JSON, default=dict)  # per-verifier pass/fail
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class Submission(Base):
    __tablename__ = "submission"
    id: Mapped[UUID] = _pk()
    session_id: Mapped[UUID] = mapped_column(ForeignKey("review_session.id"))
    reward: Mapped[int] = mapped_column(default=1)
    kind: Mapped[str] = mapped_column(String(16), default="golden")  # golden | breaker
    submitted_with_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[UUID] = _pk()
    actor: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(255), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
