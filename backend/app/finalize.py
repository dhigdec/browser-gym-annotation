"""Finalization — the last gate before a trajectory becomes a shipped sample.

A score is meaningless unless it names exactly what produced it, so finalization
binds all four together (§3.7):

    BenchmarkRun -> trajectory_version + verifier_suite + final_checkpoint
    Submission   -> task_revision + approved_version + benchmark_run

And it only runs on a version that (a) a reviewer APPROVED and (b) replays
deterministically from a clean environment against that exact suite. Both gates
matter: approval without replay ships a trajectory nobody can reproduce; replay
without approval ships one nobody read.

The replay here starts from the ROOT, not from a fork checkpoint. Restoring a
serialized checkpoint is an optimization for editing; for the deliverable, the
whole sequence has to run from a clean reset, or "it reproduces" only means "it
reproduces from the state we happened to save".
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app import checkpoints, models, replay, versions


class NotApproved(RuntimeError):
    """QC has not approved this version. The post-submission `accepted` flag is
    too late to serve as the gate — by then it has already shipped."""


class Scorer(Protocol):
    """Runs the bound verifier suite against the world the replay ended in."""

    def score(self, suite: models.VerifierSuite, world: dict | None) -> tuple[int, dict]: ...


def actions_of(db: Session, version: models.TrajectoryVersion) -> list[dict]:
    """The flattened trajectory as structured, replayable actions. Steps with no
    locator (legacy rows recorded before the action IR) are surfaced, not
    silently dropped — a shortened replay would "pass" by doing less."""
    out = []
    for s in versions.flatten(db, version):
        out.append({
            "kind": s.action_type,
            "locator": s.semantic_locator or {},
            "args": s.arguments or {},
            "stepId": str(s.id),
            "actor": s.actor,
            "expectedHash": checkpoints.hash_world(s.world_after) if s.world_after else "",
        })
    return out


def replayable(actions: list[dict]) -> tuple[bool, list[int]]:
    """Which actions carry enough to be re-executed. `navigate` needs only a URL;
    everything else needs a locator."""
    missing = [
        i for i, a in enumerate(actions)
        if a["kind"] not in ("navigate", "press") and not a["locator"]
    ]
    return (not missing), missing


def finalize(
    db: Session,
    *,
    attempt: models.ReviewSession,
    version: models.TrajectoryVersion,
    suite: models.VerifierSuite,
    executor: replay.Executor,
    gym,
    scorer: Scorer,
    annotator_id: UUID | None = None,
    kind: str = "golden",
    task_external_id: str = "",
    require_replay: bool = True,
) -> dict:
    """Replay, score, bind, freeze. Raises rather than shipping something unbound."""
    if version.attempt_id != attempt.id:
        raise versions.LineageError("that version belongs to another attempt")
    if suite.session_id != attempt.id:
        raise versions.LineageError("that verifier suite belongs to another attempt")
    if version.status != "approved":
        raise NotApproved("finalization needs a QC-approved version")

    actions = actions_of(db, version)
    if not actions:
        raise NotApproved("this version has no steps to finalize")

    result = None
    if require_replay:
        ok, missing = replayable(actions)
        if not ok:
            raise replay.ReplayRejected(
                missing[0], "this step has no semantic locator, so the trajectory cannot be replayed"
            )
        # A CLEAN reset — not a checkpoint restore. The deliverable must reproduce
        # from the task's own starting conditions.
        if gym.reset(task_external_id, attempt.seed) is None:
            raise replay.ReplayRejected(0, "could not reset the task for a clean replay")
        result = replay.replay(
            actions, executor,
            expected_hashes=[a["expectedHash"] for a in actions],
            # The clean replay must reproduce the RECORDING's protocol, clock and
            # all. Without the tick the replayed world trails by one step and a
            # correct trajectory is rejected as diverged.
            clock=replay.advance_clock(gym),
            strict=True,
        )

    final_world = (result.final_world if result else None) or (gym.world() if hasattr(gym, "world") else None)
    final_cp = checkpoints.capture(
        db, attempt_id=attempt.id, world=final_world, step_clock=len(actions),
    )
    reward, results = scorer.score(suite, final_world)

    run = models.BenchmarkRun(
        suite_id=suite.id, reward=reward, results=results,
        trajectory_version_id=version.id, final_checkpoint_id=final_cp.id,
    )
    db.add(run)
    db.flush()

    sub = models.Submission(
        session_id=attempt.id, reward=reward, kind=kind,
        task_revision=attempt.task_revision,
        approved_trajectory_version_id=version.id,
        benchmark_run_id=run.id,
        snapshot=freeze(db, attempt=attempt, version=version, suite=suite, run=run, final_checkpoint=final_cp),
    )
    db.add(sub)
    versions.set_status(db, version, "published", expected_revision=version.revision)
    db.flush()
    return {
        "submissionId": str(sub.id), "benchmarkRunId": str(run.id),
        "versionId": str(version.id), "reward": reward, "results": results,
        "finalCheckpointId": str(final_cp.id),
        "replayed": bool(result), "steps": len(actions),
    }


def freeze(
    db: Session,
    *,
    attempt: models.ReviewSession,
    version: models.TrajectoryVersion,
    suite: models.VerifierSuite,
    run: models.BenchmarkRun,
    final_checkpoint: models.EnvironmentCheckpoint,
) -> dict:
    """The deliverable, captured at submit time.

    Freezing matters because everything it references keeps moving: the canonical
    run gets re-captured, suites get edited, later benchmarks get recorded. A
    shipped sample must say what was actually reviewed and scored, not what those
    rows look like today.
    """
    verifiers = [
        {"id": v.ext_id, "level": v.level, "assertion": v.assertion, "code": v.code,
         "check": v.check_ir or None, "gym_result": v.gym_result or None,
         "added_by_human": v.added_by_human}
        for v in suite.verifiers
    ]
    lineage = [
        {"versionNo": v.version_no, "kind": v.kind, "status": v.status, "producer": v.producer,
         "forkBeforeStepId": str(v.fork_before_step_id) if v.fork_before_step_id else None}
        for v in versions.chain(db, version)
    ]
    steps = []
    for n, s in enumerate(versions.flatten(db, version)):
        after = db.get(models.EnvironmentCheckpoint, s.after_checkpoint_id) if s.after_checkpoint_id else None
        steps.append({
            "idx": n, "stepId": str(s.id), "actor": s.actor, "type": s.action_type,
            "description": s.description, "locator": s.semantic_locator or {},
            "resolved": s.resolved_target or {}, "args": s.arguments or {},
            "url": s.url_after, "screenshot": s.screenshot_url or None,
            "reasoning": s.reasoning or "", "human_intent": s.human_intent or "",
            "guidance": s.guidance_text or "",
            "world_hash": after.world_hash if after else "",
        })
    return {
        "task_revision": attempt.task_revision,
        "trajectory_version": {
            "id": str(version.id), "versionNo": version.version_no, "kind": version.kind,
            "environment_image_digest": version.environment_image_digest,
            "lineage": lineage,
        },
        "golden_trajectory": steps,
        "verifiers": verifiers,
        "suite_version": suite.version,
        "reward": run.reward,
        "overridden": run.overridden or [],
        "final_world_hash": final_checkpoint.world_hash,
        "final_checkpoint_id": str(final_checkpoint.id),
    }
