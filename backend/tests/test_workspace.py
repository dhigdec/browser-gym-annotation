"""Workspace isolation: lease lifecycle + the human/agent runtime split.

Uses a fake runtime provider so nothing real is spawned — the contract under test
is the lease bookkeeping, not uvicorn.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app import models
from app.config import settings
from app.workspace import manager
from app.workspace.provider import WorkspaceHandle


class FakeProvider:
    """Records what it was asked to do; `alive` controls health so a test can kill
    a workspace behind the manager's back."""

    kind = "local_process"

    def __init__(self) -> None:
        self.provisioned: list[str] = []
        self.terminated: list[str] = []
        self.alive: dict[str, bool] = {}
        self._n = 0

    def provision(self, *, label: str) -> WorkspaceHandle:
        self._n += 1
        ref = f"pid-{self._n}"
        self.provisioned.append(label)
        self.alive[ref] = True
        return WorkspaceHandle(
            endpoint=f"http://127.0.0.1:900{self._n}", external_ref=ref,
            runtime_kind=self.kind, image_digest="sha256:test",
        )

    def health(self, handle: WorkspaceHandle) -> bool:
        return self.alive.get(handle.external_ref, False)

    def terminate(self, handle: WorkspaceHandle) -> None:
        self.terminated.append(handle.external_ref)
        self.alive[handle.external_ref] = False


@pytest.fixture()
def iso(monkeypatch):
    """Isolation ON with a fake runtime."""
    fake = FakeProvider()
    monkeypatch.setattr(manager, "_provider", lambda: fake)
    monkeypatch.setattr(manager, "isolation_available", lambda: True)
    return fake


@pytest.fixture()
def attempt(db_session):
    task = models.Task(external_id=f"WS-{uuid4().hex[:8]}", title="t", prompt="p", source="gym")
    ann = models.Annotator(email=f"ws-{uuid4().hex[:8]}@test")
    db_session.add_all([task, ann])
    db_session.flush()
    s = models.ReviewSession(task_id=task.id, annotator_id=ann.id, source="gym")
    db_session.add(s)
    db_session.commit()
    return s


def test_isolation_off_by_default_falls_back_to_shared_gym(db_session, attempt):
    """Without isolation configured we must fall back to the SHARED gym — and the
    caller can tell, so two annotators are never silently put in one world."""
    assert manager.isolation_available() is False
    assert manager.acquire(db_session, attempt.id) is None
    assert manager.endpoint_for(db_session, attempt.id).base_url == settings.gym_url


def test_acquire_provisions_then_reuses_a_healthy_lease(db_session, attempt, iso):
    first = manager.acquire(db_session, attempt.id, annotator_id=attempt.annotator_id)
    assert first is not None and first.status == "ready"
    assert first.purpose == manager.HUMAN
    assert first.endpoint and first.external_ref
    assert first.environment_image_digest == "sha256:test"

    again = manager.acquire(db_session, attempt.id, annotator_id=attempt.annotator_id)
    assert again.id == first.id, "a healthy lease must be reused, not duplicated"
    assert len(iso.provisioned) == 1

    # and the attempt's gym calls are routed to ITS workspace, not the shared gym
    assert manager.endpoint_for(db_session, attempt.id).base_url == first.endpoint


def test_dead_workspace_is_reclaimed_and_replaced(db_session, attempt, iso):
    first = manager.acquire(db_session, attempt.id)
    iso.alive[first.external_ref] = False  # process died behind our back

    second = manager.acquire(db_session, attempt.id)
    assert second.id != first.id, "a dead lease must be replaced, not handed back"
    assert first.external_ref in iso.terminated, "the dead lease must be reclaimed"
    db_session.refresh(first)
    assert first.status == "terminated"


def test_human_and_agent_branch_workspaces_are_separate(db_session, attempt, iso):
    """The core isolation rule: an agent branch run gets its OWN runtime, so it can
    never reset the world out from under the human mid-review."""
    human = manager.acquire(db_session, attempt.id, purpose=manager.HUMAN)
    branch = manager.acquire(db_session, attempt.id, purpose=manager.AGENT_BRANCH)

    assert human.id != branch.id
    assert human.endpoint != branch.endpoint, "human and agent must not share a gym process"
    assert {human.purpose, branch.purpose} == {manager.HUMAN, manager.AGENT_BRANCH}
    # the live browser still resolves to the HUMAN workspace
    assert manager.endpoint_for(db_session, attempt.id).base_url == human.endpoint

    # tearing down the branch worker leaves the human workspace untouched
    manager.release(db_session, branch)
    db_session.refresh(human)
    assert human.status == "ready"
    assert manager.endpoint_for(db_session, attempt.id).base_url == human.endpoint


def test_touch_extends_the_inactivity_window(db_session, attempt, iso):
    lease = manager.acquire(db_session, attempt.id)
    lease.expires_at = datetime.utcnow() + timedelta(minutes=1)
    db_session.commit()
    before = lease.expires_at

    manager.touch(db_session, lease)
    assert lease.expires_at > before, "active work must not be reaped mid-annotation"


def test_reaper_reclaims_only_expired_leases(db_session, attempt, iso):
    live = manager.acquire(db_session, attempt.id, purpose=manager.HUMAN)
    doomed = manager.acquire(db_session, attempt.id, purpose=manager.AGENT_BRANCH)
    doomed.expires_at = datetime.utcnow() - timedelta(minutes=5)
    db_session.commit()

    assert manager.reap_expired(db_session) == 1
    db_session.refresh(doomed)
    db_session.refresh(live)
    assert doomed.status == "terminated" and doomed.external_ref in iso.terminated
    assert live.status == "ready", "an active lease must survive the reaper"


def test_restart_reconciliation_drops_orphans_and_adopts_live(db_session, attempt, iso):
    """After a restart, a lease either still has a live process (adopt) or does not
    (terminate) — otherwise we leak processes and serve dead endpoints."""
    alive = manager.acquire(db_session, attempt.id, purpose=manager.HUMAN)
    orphan = manager.acquire(db_session, attempt.id, purpose=manager.AGENT_BRANCH)
    iso.alive[orphan.external_ref] = False

    adopted = manager.reconcile_on_startup(db_session)
    assert adopted == 1
    db_session.refresh(alive)
    db_session.refresh(orphan)
    assert alive.status == "ready"
    assert orphan.status == "terminated"


def test_failed_provisioning_does_not_wedge_the_attempt(db_session, attempt, monkeypatch):
    class Broken(FakeProvider):
        def provision(self, *, label: str):
            raise RuntimeError("no port available")

    monkeypatch.setattr(manager, "_provider", lambda: Broken())
    monkeypatch.setattr(manager, "isolation_available", lambda: True)
    with pytest.raises(RuntimeError, match="workspace provisioning failed"):
        manager.acquire(db_session, attempt.id)

    # the failed lease is closed out, not left dangling as "provisioning"
    rows = db_session.scalars(
        select(models.WorkspaceLease).where(models.WorkspaceLease.attempt_id == attempt.id)
    ).all()
    assert rows and all(r.status == "terminated" for r in rows)


def test_agent_run_uses_its_own_workspace_and_never_the_humans(db_session, attempt, iso, monkeypatch, _session_factory):
    """THE isolation rule, end to end: a batch agent run must get its own
    short-lived branch workspace and release it, leaving the annotator's live
    workspace untouched. Running against the human's gym would reset the world
    out from under them mid-review."""
    from app.api import gym as gym_api

    human = manager.acquire(db_session, attempt.id, purpose=manager.HUMAN)
    human_endpoint = human.endpoint

    monkeypatch.setattr(gym_api.workspace, "isolation_available", lambda: True)
    # the job opens its OWN session in production; point that at the test DB
    monkeypatch.setattr(gym_api, "SessionLocal", _session_factory)

    used: list[str] = []
    with gym_api._agent_workspace(str(attempt.id)) as gym:
        used.append(gym.base_url)

    assert used and used[0] != human_endpoint, "the agent must not drive the human's workspace"

    db_session.expire_all()
    db_session.refresh(human)
    assert human.status == "ready", "the human workspace must survive the agent run"
    assert manager.endpoint_for(db_session, attempt.id).base_url == human_endpoint

    # the branch worker was reclaimed when the run finished
    branch = manager.active_lease(db_session, attempt.id, purpose=manager.AGENT_BRANCH)
    assert branch is None, "the branch worker must be torn down after the run"


def test_agent_workspace_falls_back_to_the_shared_gym_without_isolation(db_session, attempt):
    """Without isolation the behaviour must be exactly what it was — the module,
    same seams — so nothing silently changes for existing flows."""
    from app import gym_client
    from app.api import gym as gym_api

    with gym_api._agent_workspace(str(attempt.id)) as gym:
        assert gym is gym_client
