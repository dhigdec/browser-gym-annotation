"""Core platform schema (Postgres).

A normalized, foreign-keyed relational model for the annotation platform. The
gym owns the live world state; this DB owns the operational record — tasks and
their seed state, per-annotator review sessions, the recorded trajectories +
steps, the verifier suites and their runs, submissions, and an audit log.

Relationships (all FK-backed, cascade where a child cannot outlive its parent):

    annotator ─┐
               ├─< review_session ─┬─< verifier_suite ─┬─< verifier
    task ──────┘        │          │                   └─< benchmark_run
                        │          ├─< trajectory ──────< trajectory_step
                        │          ├─< trajectory_branch (self-referential)
                        │          └─< submission
                        └─< audit_log (nullable)

Enums are short strings for now; tighten to native enums with the first Alembic
migration (create_all bootstraps the schema in dev).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _pk() -> Mapped[UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid4)


def _fk(target: str, *, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[UUID]:
    return mapped_column(ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


class Annotator(Base):
    __tablename__ = "annotator"
    id: Mapped[UUID] = _pk()
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="annotator")  # annotator | reviewer | admin
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    sessions: Mapped[list["ReviewSession"]] = relationship(back_populates="annotator")


class Task(Base):
    """A reviewable task + its initial seed state. `source` distinguishes the
    hand-authored fixtures from the 312 real gym tasks; `seed_state` holds the
    initial world snapshot so every task starts from a known, reproducible state."""

    __tablename__ = "task"
    id: Mapped[UUID] = _pk()
    external_id: Mapped[str] = mapped_column(String(96), unique=True, index=True)  # "GYM-2041" | "A1/buy_wireless_mouse"
    source: Mapped[str] = mapped_column(String(16), default="fixture", index=True)  # fixture | gym
    title: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(96), default="")
    difficulty: Mapped[str] = mapped_column(String(16), default="")  # easy | medium | hard
    priority: Mapped[str] = mapped_column(String(16), default="Medium")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    start_url: Mapped[str] = mapped_column(Text, default="")
    seed_state: Mapped[dict] = mapped_column(JSON, default=dict)  # initial world snapshot
    meta: Mapped[dict] = mapped_column(JSON, default=dict)  # constraints, allowed sites, run summary
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    sessions: Mapped[list["ReviewSession"]] = relationship(back_populates="task")


class ReviewSession(Base):
    __tablename__ = "review_session"
    id: Mapped[UUID] = _pk()
    task_id: Mapped[UUID] = _fk("task.id", ondelete="RESTRICT")
    annotator_id: Mapped[UUID | None] = _fk("annotator.id", nullable=True, ondelete="SET NULL")
    source: Mapped[str] = mapped_column(String(16), default="fixture")  # fixture | gym
    seed: Mapped[int] = mapped_column(Integer, default=0)
    agent: Mapped[str] = mapped_column(String(32), default="")  # the agent whose run is under review
    # draft | steps_approved | verifiers_generated | benchmark_run | submitted
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    rerun_from: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
    updated_at: Mapped[datetime] = mapped_column(default=func.now(), onupdate=func.now())

    task: Mapped[Task] = relationship(back_populates="sessions")
    annotator: Mapped[Annotator | None] = relationship(back_populates="sessions")
    suites: Mapped[list["VerifierSuite"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    trajectories: Mapped[list["Trajectory"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    branches: Mapped[list["TrajectoryBranch"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class Trajectory(Base):
    """A recorded agent run under review (the fixture trace, or a real gym run)."""

    __tablename__ = "trajectory"
    id: Mapped[UUID] = _pk()
    session_id: Mapped[UUID] = _fk("review_session.id")
    agent: Mapped[str] = mapped_column(String(32), default="")
    seed: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(16), default="fixture")  # fixture | gym
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    session: Mapped[ReviewSession] = relationship(back_populates="trajectories")
    steps: Mapped[list["TrajectoryStep"]] = relationship(back_populates="trajectory", cascade="all, delete-orphan", order_by="TrajectoryStep.idx")


class TrajectoryStep(Base):
    __tablename__ = "trajectory_step"
    id: Mapped[UUID] = _pk()
    trajectory_id: Mapped[UUID] = _fk("trajectory.id")
    idx: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(16), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tab_id: Mapped[str] = mapped_column(String(32), default="")
    screenshot_url: Mapped[str] = mapped_column(Text, default="")
    reasoning: Mapped[str] = mapped_column(Text, default="")
    url_after: Mapped[str] = mapped_column(Text, default="")

    trajectory: Mapped[Trajectory] = relationship(back_populates="steps")


class VerifierSuite(Base):
    __tablename__ = "verifier_suite"
    id: Mapped[UUID] = _pk()
    session_id: Mapped[UUID] = _fk("review_session.id")
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    session: Mapped[ReviewSession] = relationship(back_populates="suites")
    verifiers: Mapped[list["Verifier"]] = relationship(back_populates="suite", cascade="all, delete-orphan")
    runs: Mapped[list["BenchmarkRun"]] = relationship(back_populates="suite", cascade="all, delete-orphan")


class Verifier(Base):
    __tablename__ = "verifier"
    id: Mapped[UUID] = _pk()
    suite_id: Mapped[UUID] = _fk("verifier_suite.id")
    ext_id: Mapped[str] = mapped_column(String(64), default="")  # stable authoring id (e.g. "sa1") for result keying
    level: Mapped[str] = mapped_column(String(16))  # ui | backend | semantic | process | safety
    assertion: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    check_ir: Mapped[dict] = mapped_column(JSON, default=dict)  # executable IR (M5)
    gym_result: Mapped[str] = mapped_column(String(8), default="")  # real milestone result (M8): pass | fail
    fails_until_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by_human: Mapped[bool] = mapped_column(Boolean, default=False)

    suite: Mapped[VerifierSuite] = relationship(back_populates="verifiers")


class BenchmarkRun(Base):
    __tablename__ = "benchmark_run"
    id: Mapped[UUID] = _pk()
    suite_id: Mapped[UUID] = _fk("verifier_suite.id")
    reward: Mapped[int] = mapped_column(default=0)
    results: Mapped[dict] = mapped_column(JSON, default=dict)  # per-verifier pass/fail
    overridden: Mapped[list] = mapped_column(JSON, default=list)  # verifier ids a human forced to pass
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    suite: Mapped[VerifierSuite] = relationship(back_populates="runs")


class Submission(Base):
    __tablename__ = "submission"
    id: Mapped[UUID] = _pk()
    session_id: Mapped[UUID] = _fk("review_session.id")
    reward: Mapped[int] = mapped_column(default=1)
    kind: Mapped[str] = mapped_column(String(16), default="golden")  # golden | breaker
    submitted_with_override: Mapped[bool] = mapped_column(Boolean, default=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)  # a reviewer adjudicated this the accepted golden (QA)
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    session: Mapped[ReviewSession] = relationship(back_populates="submissions")


class TrajectoryBranch(Base):
    """An immutable corrected re-run branch. Every correction creates a new
    version (chained via parent_id); nothing is overwritten. `mode` records how
    the continuation was produced — deterministic (oracle/gold path), or `agent`
    when a live agent re-runs from the corrected state (M6b)."""

    __tablename__ = "trajectory_branch"
    id: Mapped[UUID] = _pk()
    session_id: Mapped[UUID] = _fk("review_session.id")
    parent_id: Mapped[UUID | None] = _fk("trajectory_branch.id", nullable=True, ondelete="SET NULL")
    from_step: Mapped[int] = mapped_column()
    correction: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(16), default="deterministic")  # deterministic | agent
    steps: Mapped[dict] = mapped_column(JSON, default=dict)  # the continuation steps
    created_at: Mapped[datetime] = mapped_column(default=func.now())

    session: Mapped[ReviewSession] = relationship(back_populates="branches")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[UUID] = _pk()
    session_id: Mapped[UUID | None] = _fk("review_session.id", nullable=True, ondelete="SET NULL")
    actor: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=func.now())
