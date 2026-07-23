"""Environment checkpoints: what gets captured, and that divergence fails closed."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app import checkpoints, models


@pytest.fixture()
def attempt(db_session):
    task = models.Task(external_id=f"CP-{uuid4().hex[:8]}", title="t", prompt="p", source="gym")
    ann = models.Annotator(email=f"cp-{uuid4().hex[:8]}@test")
    db_session.add_all([task, ann])
    db_session.flush()
    s = models.ReviewSession(task_id=task.id, annotator_id=ann.id, source="gym")
    db_session.add(s)
    db_session.commit()
    return s


WORLD = {"task_id": "M40/x", "seed": 0, "step": 3, "shop": {"cart": {"items": [{"product_id": "p1"}]}}}


# --------------------------------------------------------------------------- hashing
def test_hash_is_stable_across_key_order():
    """Key order is an encoding detail; it must not read as divergence."""
    a = {"shop": {"b": 2, "a": 1}, "seed": 0}
    b = {"seed": 0, "shop": {"a": 1, "b": 2}}
    assert checkpoints.hash_world(a) == checkpoints.hash_world(b)


def test_hash_ignores_volatile_noise():
    """Flash messages / action logs churn on every read. Hashing them would make
    the divergence guard fire constantly and be switched off."""
    quiet = dict(WORLD)
    noisy = {**WORLD, "flash_messages": ["saved!"], "action_log": [{"kind": "view"}]}
    assert checkpoints.hash_world(quiet) == checkpoints.hash_world(noisy)


def test_hash_detects_real_state_change():
    changed = {**WORLD, "shop": {"cart": {"items": []}}}  # the cart was emptied
    assert checkpoints.hash_world(WORLD) != checkpoints.hash_world(changed)


def test_empty_world_hashes_to_empty_not_a_constant():
    """An absent capture must not collide with a real state, or a missing
    checkpoint would silently 'match'."""
    assert checkpoints.hash_world(None) == ""
    assert checkpoints.hash_world({}) == ""
    assert checkpoints.hash_world(WORLD) != ""


# --------------------------------------------------------------------------- capture
def test_capture_persists_the_full_browser_context(db_session, attempt):
    """world_after alone cannot restore a browser — the tab list, cookies, storage
    and scroll all have to survive too."""
    cp = checkpoints.capture(
        db_session,
        attempt_id=attempt.id,
        world=WORLD,
        backend_state={"cart": {"items": []}},
        step_clock=3,
        environment_image_digest="sha256:img",
        browser={
            "url": "http://localhost:8000/cart",
            "activeTab": 1,
            "tabs": ["http://localhost:8000/", "http://localhost:8000/cart"],
            "cookies": [{"name": "sid", "value": "abc"}],
            "storageState": {"origins": []},
            "localStorage": {"k": "v"},
            "viewport": {"width": 1280, "height": 800},
            "devicePixelRatio": 1.0,
            "scroll": {"x": 0, "y": 420},
        },
        dom_text="<html>cart</html>",
    )
    db_session.commit()

    assert cp.url.endswith("/cart")
    assert len(cp.tabs) == 2, "the FULL tab list must survive, not just the active one"
    assert cp.active_tab == "1"
    assert cp.cookies and cp.local_storage == {"k": "v"}
    assert cp.scroll == {"x": 0, "y": 420}
    assert cp.step_clock == 3
    assert cp.environment_image_digest == "sha256:img"
    assert cp.world_hash == checkpoints.hash_world(WORLD)
    assert cp.dom_hash == checkpoints.hash_dom("<html>cart</html>")


def test_capture_works_without_a_live_browser(db_session, attempt):
    """An agent-only run has no attached browser; it must still checkpoint its world."""
    cp = checkpoints.capture(db_session, attempt_id=attempt.id, world=WORLD)
    db_session.commit()
    assert cp.world_hash and cp.url == "" and cp.tabs == []


def test_artifacts_are_registered_with_a_digest(db_session, attempt):
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 64
    art = checkpoints.add_artifact(db_session, kind="screenshot", uri="s3://shots/1.png", data=png)
    cp = checkpoints.capture(db_session, attempt_id=attempt.id, world=WORLD, screenshot_artifact_id=art.id)
    db_session.commit()
    assert art.sha256 and art.bytes == len(png)
    assert cp.screenshot_artifact_id == art.id


# --------------------------------------------------------------------------- divergence
def test_matching_world_passes_the_guard(db_session, attempt):
    cp = checkpoints.capture(db_session, attempt_id=attempt.id, world=WORLD)
    checkpoints.assert_matches(cp, dict(WORLD))  # must not raise


def test_diverged_world_fails_closed(db_session, attempt):
    """A silently-diverged replay yields a golden trajectory that does not
    reproduce — worse than no trajectory. It must raise."""
    cp = checkpoints.capture(db_session, attempt_id=attempt.id, world=WORLD)
    with pytest.raises(checkpoints.DivergenceError) as ei:
        checkpoints.assert_matches(cp, {**WORLD, "shop": {"cart": {"items": []}}}, at="step 4")
    assert "step 4" in str(ei.value)


def test_a_hashless_checkpoint_cannot_claim_a_match(db_session, attempt):
    cp = checkpoints.capture(db_session, attempt_id=attempt.id, world=None)
    checkpoints.assert_matches(cp, {"anything": True})  # no hash recorded => no claim


# --------------------------------------------------------------------------- restore
class FakeGym:
    def __init__(self, world_after_load):
        self.world_after_load = world_after_load
        self.loaded = None

    def load_state(self, task_id, seed, state, step=None):
        self.loaded = (task_id, seed, step)
        return {"ok": True}

    def world(self):
        return self.world_after_load


def test_restore_loads_then_verifies(db_session, attempt):
    cp = checkpoints.capture(db_session, attempt_id=attempt.id, world=WORLD, step_clock=3)
    gym = FakeGym(dict(WORLD))
    assert checkpoints.restore(cp, gym, task_id="M40/x", seed=0) is True
    assert gym.loaded == ("M40/x", 0, 3), "the step clock must be restored too"


def test_restore_raises_when_the_loaded_world_is_not_the_recorded_one(db_session, attempt):
    """The serialized load is an optimization; the hash comparison is what makes it
    trustworthy. A load that lands somewhere else must not be reported as success."""
    cp = checkpoints.capture(db_session, attempt_id=attempt.id, world=WORLD)
    gym = FakeGym({**WORLD, "shop": {"cart": {"items": [{"product_id": "OTHER"}]}}})
    with pytest.raises(checkpoints.DivergenceError):
        checkpoints.restore(cp, gym, task_id="M40/x", seed=0)


def test_restore_reports_failure_when_the_gym_cannot_load(db_session, attempt):
    class Broken(FakeGym):
        def load_state(self, *a, **k):
            return None

    cp = checkpoints.capture(db_session, attempt_id=attempt.id, world=WORLD)
    assert checkpoints.restore(cp, Broken(None), task_id="M40/x", seed=0) is False
