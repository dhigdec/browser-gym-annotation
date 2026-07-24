"""Agent branch runs — the handoff between a human workspace and a batch agent.

The isolation rule (§2.1), stated as a sequence:

    capture the branch's starting checkpoint
    → launch an ISOLATED worker from it (never the annotator's own gym)
    → persist the result as a PENDING CHILD version
    → leave the human workspace untouched
    → the human explicitly selects the child if they want it

The last two lines are the load-bearing ones. A completing job never advances
`active_version_id`, which is exactly what makes out-of-order completions safe: a
slow run that lands after the annotator moved on becomes an unselected candidate
instead of silently overwriting their decision.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import checkpoints, models, recorder, versions

QUEUED, RUNNING, DONE, ERROR = "queued", "running", "done", "error"


class CapExceeded(RuntimeError):
    """The attempt has used its agent runs. Counted on the ATTEMPT so sibling
    branches cannot reset it by forking."""


def find_by_key(db: Session, attempt_id: UUID, key: str) -> models.AgentRunJob | None:
    if not key:
        return None
    return db.scalar(
        select(models.AgentRunJob).where(
            models.AgentRunJob.attempt_id == attempt_id, models.AgentRunJob.idempotency_key == key
        )
    )


def enqueue(
    db: Session,
    *,
    attempt: models.ReviewSession,
    source_version: models.TrajectoryVersion,
    step: models.TrajectoryStep,
    mode: str = "before",
    correction: str = "",
    agent: str = "llm",
    created_by_id: UUID | None = None,
    idempotency_key: str = "",
    max_calls: int | None = None,
) -> tuple[models.AgentRunJob, models.TrajectoryVersion]:
    """Create the candidate child + the job bound to the EXACT source it forked
    from. Returns the existing job unchanged when the key was already used — a
    retried request must not spawn a second run or burn a second call."""
    dup = find_by_key(db, attempt.id, idempotency_key)
    if dup is not None:
        child = db.get(models.TrajectoryVersion, dup.result_version_id) if dup.result_version_id else None
        return dup, child

    if max_calls is not None and int(attempt.agent_call_count or 0) >= max_calls:
        raise CapExceeded(f"this attempt has used its {max_calls} agent runs — finish it manually")

    make = versions.fork_before if mode == "before" else versions.continue_after
    child = make(
        db, parent=source_version, step=step, kind=versions.CORRECTION,
        producer=agent, model_config={"agent": agent, "correction": correction},
        created_by_id=created_by_id,
    )
    job = models.AgentRunJob(
        attempt_id=attempt.id,
        source_version_id=source_version.id,
        source_checkpoint_id=child.fork_checkpoint_id,
        expected_attempt_revision=attempt.revision,
        result_version_id=child.id,
        status=QUEUED,
        idempotency_key=idempotency_key,
        counts_against_cap=True,
    )
    db.add(job)
    db.flush()
    return job, child


def start(db: Session, job: models.AgentRunJob, *, owner: str = "") -> None:
    job.status = RUNNING
    job.owner = owner
    job.heartbeat_at = datetime.utcnow()
    job.provider_request_started_at = datetime.utcnow()
    db.flush()


def heartbeat(db: Session, job: models.AgentRunJob) -> None:
    job.heartbeat_at = datetime.utcnow()
    db.flush()


def fail(db: Session, job: models.AgentRunJob, error: str, *, infrastructure: bool = False) -> None:
    """A confirmed INFRASTRUCTURE failure must not burn one of the annotator's
    runs — they did not get a model attempt out of it."""
    job.status = ERROR
    job.error = error[:2000]
    job.counts_against_cap = not infrastructure
    db.flush()


def complete(
    db: Session,
    job: models.AgentRunJob,
    *,
    attempt: models.ReviewSession,
    child: models.TrajectoryVersion,
    steps: list[dict],
    trajectory_id: UUID,
    guidance: str = "",
    guidance_author_id: UUID | None = None,
) -> models.TrajectoryVersion:
    """Persist the run's steps as the child's suffix and mark the job done.

    Deliberately does NOT touch `attempt.active_version_id`: selection is a
    separate, versioned command.
    """
    now = datetime.utcnow()
    prev_cp = db.get(models.EnvironmentCheckpoint, job.source_checkpoint_id) if job.source_checkpoint_id else None
    for st in steps:
        after_cp = None
        if st.get("world_after"):
            after_cp = checkpoints.capture(
                db, attempt_id=attempt.id, world=st["world_after"],
                backend_state=st.get("snapshot_after") or {},
                step_clock=(prev_cp.step_clock + 1) if prev_cp is not None else 0,
                browser={"url": st.get("url_after") or ""},
            )
        versions.append_step(
            db, child, trajectory_id=trajectory_id, actor="agent",
            action_type=st.get("action_kind") or st.get("type") or "",
            description=st.get("description", ""),
            reasoning=(st.get("reasoning") or "").strip(),
            url_after=st.get("url_after") or st.get("url") or "",
            screenshot_url=st.get("image") or "",
            arguments=st.get("action_args") or {},
            # Derive the locator from the recorded selector. Without it the step
            # has no replayable target, finalization refuses the whole trajectory,
            # and an agent-assisted correction can be created, selected and
            # approved but never actually shipped — the platform's primary
            # workflow, dead at the last gate.
            semantic_locator=recorder.locator_from_selector((st.get("action_args") or {}).get("selector", "")),
            world_after=st.get("world_after") or None,
            before_checkpoint_id=prev_cp.id if prev_cp is not None else None,
            after_checkpoint_id=after_cp.id if after_cp is not None else None,
            # The reviewer's instruction is provenance on every step it produced —
            # never reconstructed afterwards as if the agent had reasoned it.
            guidance_text=guidance,
            guidance_author_id=guidance_author_id,
            intervention_at=now if guidance else None,
        )
        prev_cp = after_cp or prev_cp

    job.status = DONE
    job.result_version_id = child.id
    if job.counts_against_cap:
        versions.count_agent_call(db, attempt)
    db.flush()
    return child


def reap_stale(db: Session, *, older_than: datetime) -> int:
    """A worker that died mid-run leaves a job RUNNING forever, which would block
    the attempt behind a job nobody is executing."""
    rows = db.scalars(
        select(models.AgentRunJob).where(
            models.AgentRunJob.status == RUNNING, models.AgentRunJob.heartbeat_at < older_than
        )
    ).all()
    for j in rows:
        fail(db, j, "worker stopped heartbeating", infrastructure=True)
    return len(rows)
