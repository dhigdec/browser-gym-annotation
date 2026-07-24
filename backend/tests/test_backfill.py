"""Replay-backfill — recovering a world trail that was never recorded, without
ever inventing one.

The whole value of this module is the SKIP. A backfill that writes a world it
could not check produces forks that restore the wrong state and trajectories that
do not reproduce, and nothing downstream would notice. So these tests care much
more about what is refused than about what is written.

Everything here runs against a fake gym and a fake executor: no browser, no
network, no gym process.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app import backfill, canonical, checkpoints, models

TASK = "M40/bogus_pricematch"


# --------------------------------------------------------------------------- fakes
def world_at(step: int, orders: list[str]) -> dict:
    """The world the fake gym reports after `step` actions. Mirrors the real one
    in the way that matters here: the step counter is part of the world, so the
    /_harness/verify call that sets it is load-bearing rather than decorative."""
    return {"task_id": TASK, "seed": 0, "step": step, "shop": {"orders": list(orders)}}


class FakeGym:
    """A gym whose world only moves when the executor moves it."""

    def __init__(self, seed_world: dict | None = None):
        self.seed = seed_world or world_at(0, [])
        self.state = copy.deepcopy(self.seed)
        self.verified: list[tuple[str, int]] = []
        self.ticks: list[int] = []
        self.reachable = True

    def reset(self, task_id: str, seed: int) -> dict | None:
        if not self.reachable:
            return None
        self.state = copy.deepcopy(self.seed)
        return {"ok": True, "task_id": task_id, "seed": seed}

    def verify(self, url: str, step: int) -> dict:
        self.verified.append((url, step))
        self.state["step"] = step
        return {"score": 0.0}

    def tick(self, step: int) -> dict:
        self.ticks.append(step)
        return {"now": step}

    def world(self) -> dict:
        return copy.deepcopy(self.state)

    def snapshot(self) -> dict:
        return {
            "task_id": TASK, "step": self.state["step"], "current_user_id": "u_alice",
            "cart_item_count": 0, "orders_count": len(self.state["shop"]["orders"]),
            "returns_count": 0, "subscriptions_count": 0, "applied_promo": None,
        }


class FakeExecutor:
    """Applies an action's effect to the fake gym's world, or refuses it. `absent`
    names the locators that no longer resolve — the ordinary way an archived run
    stops replaying."""

    def __init__(self, gym: FakeGym, effects: dict | None = None, absent: set | None = None):
        self.gym = gym
        self.effects = effects or {}
        self.absent = absent or set()
        self.performed: list[tuple[str, dict]] = []

    def act(self, kind: str, locator: dict | None, args: dict | None) -> dict:
        target = (locator or {}).get("testId") or (locator or {}).get("name") or ""
        if target in self.absent:
            return {"ok": False, "error": "no element matched the locator"}
        self.performed.append((kind, dict(locator or {})))
        for order in self.effects.get(target, []):
            self.gym.state["shop"]["orders"].append(order)
        return {"ok": True, "resolved": {"selector": f"[data-test-id='{target}']", "url": "/account/orders"}}


def click(test_id: str, world: dict | None = None, snapshot: dict | None = None) -> dict:
    step = {
        "step_idx": 0, "action_kind": "click",
        "action_args": {"selector": f"[data-test-id='{test_id}']"},
        "url_after": "http://localhost:8000/account/orders",
        "reasoning": "", "snapshot_after": snapshot,
    }
    if world is not None:
        step["world_after"] = world
    return step


def archived(steps: list[dict], *, task_id: str = TASK, path: str = "M40_bogus_pricematch__0__abc.jsonl") -> backfill.ArchivedRun:
    for i, s in enumerate(steps):
        s["step_idx"] = i
    return backfill.ArchivedRun(
        path=Path(path),
        payload={
            "episode_id": "abc", "task_id": task_id, "seed": 0, "agent_name": "openai[gpt-5.5]",
            "task_brief": "get the refund", "task_difficulty": "hard", "task_category": "M",
            "initial_url": "http://localhost:8000/market", "steps": steps,
            "verifier_result": {"score": 0.0, "success": False, "all_milestones": [
                {"name": "refund_requested", "weight": 1, "required": True, "fired_at_step": -1},
            ]},
        },
    )


def replay(run: backfill.ArchivedRun, *, effects=None, absent=None, accept=backfill.WORLD, **kw):
    gym = FakeGym()
    ex = FakeExecutor(gym, effects=effects, absent=absent)
    return backfill.reconstruct(run, gym, ex, accept=accept, **kw), gym, ex


# --------------------------------------------------------------------------- the decision
def test_a_step_is_accepted_only_when_its_world_matches_the_recording():
    """The single claim this module makes: the world it hands back is the world
    that was recorded, byte for byte after normalization."""
    run = archived([click("btn-refund", world=world_at(0, ["ORD-1"]))])
    recon, _, _ = replay(run, effects={"btn-refund": ["ORD-1"]})
    assert recon.accepted == 1
    assert recon.steps[0].evidence == backfill.WORLD


def test_a_reconstruction_that_disagrees_with_the_recording_is_skipped():
    """The action landed and the replay produced *a* world — just not the one the
    archive says this step produced. Keeping it would be the whole failure mode."""
    run = archived([click("btn-refund", world=world_at(0, ["ORD-1"]))])
    recon, _, ex = replay(run, effects={"btn-refund": ["ORD-DIFFERENT"]})
    assert ex.performed, "the action still ran — this is a state disagreement, not a failure to act"
    assert recon.accepted == 0
    assert recon.steps[0].evidence == backfill.NONE


def test_the_step_counter_is_advanced_through_verify_for_every_step():
    """/_harness/verify is what sets `s.step`, and the recorded world was hashed
    with it. Omitting the call reconstructs step 0 and diverges on every step
    after — which is how this was found."""
    run = archived([click("a", world=world_at(0, [])), click("b", world=world_at(1, []))])
    recon, gym, _ = replay(run)
    assert [step for _, step in gym.verified] == [0, 1]
    assert recon.accepted == 2


def test_an_action_that_no_longer_resolves_does_not_stop_the_replay():
    """Measured on the real archive: three tasks recovered MORE worlds than they
    executed actions. Acceptance is absolute, so a later step that lands on the
    recorded world is correct however the replay got there."""
    run = archived([
        click("gone", world=world_at(0, [])),
        click("btn-refund", world=world_at(1, ["ORD-1"])),
    ])
    recon, _, _ = replay(run, effects={"btn-refund": ["ORD-1"]}, absent={"gone"})
    assert recon.executed == 1
    assert recon.steps[1].accepted, "the replay continued past the action that did not land"
    assert recon.steps[0].accepted, \
        "a step is judged by the state it left, not by whether the click landed — this one changed nothing"


def test_a_mark_addressed_action_without_role_or_name_is_reported_unreplayable():
    """A mark id indexes an overlay that existed only for the screenshot the agent
    saw. Guessing at it would produce a confident wrong world."""
    step = {"step_idx": 0, "action_kind": "click_mark", "action_args": {"mark_id": 12}}
    recon, _, _ = replay(archived([step]))
    assert recon.steps[0].accepted is False
    assert "not replayable" in recon.steps[0].error


def test_the_seed_world_disagreeing_refuses_the_entire_run():
    """A different task revision seeds a different world, and no per-step check can
    catch it — every step after would be checked against the wrong baseline."""
    run = archived([click("a", world=world_at(0, []))])
    gym = FakeGym()
    recon = backfill.reconstruct(
        run, gym, FakeExecutor(gym), expected_seed_world=world_at(0, ["SOMETHING-ELSE"])
    )
    assert recon.refused
    assert recon.steps == [], "nothing is replayed once the starting state is known to be wrong"


# --------------------------------------------------------------------------- evidence levels
def test_a_summary_only_step_is_not_accepted_by_default():
    """304 of the 315 archived tasks recorded only a counts summary. It is a real
    check but a coarse one, so keeping those worlds is an explicit choice."""
    snap = {"current_user_id": "u_alice", "orders_count": 1, "cart_item_count": 0}
    run = archived([click("btn-refund", snapshot=snap)])
    recon, _, _ = replay(run, effects={"btn-refund": ["ORD-1"]})
    assert recon.accepted == 0
    assert recon.steps[0].evidence == backfill.SNAPSHOT, "the evidence is reported even when it is not kept"


def test_summary_evidence_is_kept_when_the_operator_asks_for_it():
    snap = {"current_user_id": "u_alice", "orders_count": 1, "cart_item_count": 0}
    run = archived([click("btn-refund", snapshot=snap)])
    recon, _, _ = replay(run, effects={"btn-refund": ["ORD-1"]}, accept=backfill.SNAPSHOT)
    assert recon.accepted == 1


def test_summary_evidence_does_not_certify_a_step_whose_action_never_landed():
    """Measured on the oracle archive: A4/home_office_bundle executed 14 of its 26
    actions and still agreed on all 26 snapshots, because cart and order counts
    never moved. Counts alone would certify twelve steps that never happened."""
    snap = {"current_user_id": "u_alice", "orders_count": 0, "cart_item_count": 0}
    run = archived([click("gone", snapshot=snap)])
    recon, _, _ = replay(run, absent={"gone"}, accept=backfill.SNAPSHOT)
    assert recon.steps[0].evidence == backfill.SNAPSHOT
    assert recon.accepted == 0, "the counts agreed, but nothing happened to make them agree"


def test_a_summary_that_disagrees_is_refused_even_at_the_lower_bar():
    snap = {"current_user_id": "u_alice", "orders_count": 4, "cart_item_count": 0}
    run = archived([click("btn-refund", snapshot=snap)])
    recon, _, _ = replay(run, effects={"btn-refund": ["ORD-1"]}, accept=backfill.SNAPSHOT)
    assert recon.accepted == 0


def test_a_recorded_world_that_disagrees_never_falls_back_to_the_summary():
    """Otherwise a step whose world is provably wrong gets accepted on a count of
    three orders — the strongest available evidence has to be the one that rules."""
    snap = {"current_user_id": "u_alice", "orders_count": 1, "cart_item_count": 0}
    run = archived([click("btn-refund", world=world_at(0, ["ORD-DIFFERENT"]), snapshot=snap)])
    recon, _, _ = replay(run, effects={"btn-refund": ["ORD-1"]}, accept=backfill.SNAPSHOT)
    assert recon.accepted == 0


def test_the_recorded_step_counter_is_not_compared():
    """Older captures serialized `snapshot_after` by reference to a mutable state
    object, so every step reports the run's FINAL step. Comparing it would reject
    every reconstruction of those runs for an artefact of how they were saved."""
    snap = {"current_user_id": "u_alice", "orders_count": 0, "cart_item_count": 0, "step": 99}
    run = archived([click("a", snapshot=snap)])
    recon, _, _ = replay(run, accept=backfill.SNAPSHOT)
    assert recon.accepted == 1


# --------------------------------------------------------------------------- action translation
@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"selector": "[data-test-id='link-order-ORD-5290']"}, {"testId": "link-order-ORD-5290"}),
        ({"selector": "#email"}, {"id": "email"}),
        ({"selector": "[name='qty']"}, {"name": "qty"}),
        ({"selector": "form.checkout > button"}, {"css": "form.checkout > button"}),
        ({"role": "button", "name": "Place order", "mark_id": 3}, {"role": "button", "name": "Place order"}),
        ({"x": 100, "y": 200}, {}),
    ],
)
def test_an_archived_selector_becomes_the_locator_the_executor_speaks(args, expected):
    """The executor resolves testId and id most durably; passing the raw CSS
    through would work today and rot at the first markup change."""
    assert backfill.semantic_locator(args) == expected


@pytest.mark.parametrize(
    ("kind", "args", "expected_kind", "expected_args"),
    [
        ("key_press", {"key": "Enter"}, "press", {"key": "Enter"}),
        ("scroll_by", {"amount_px": 600, "direction": "up"}, "scroll", {"amount_px": 600, "direction": "up"}),
        ("open_tab", {"url": "/mail", "tab_index": 1}, "open_tab", {"url": "/mail"}),
        ("switch_tab", {"tab_index": 2}, "switch_tab", {"tab_index": 2}),
        ("wait", {}, "wait", {}),
    ],
)
def test_the_archives_action_names_are_translated_to_the_executors(kind, args, expected_kind, expected_args):
    """`key_press` and `scroll_by` alone are 10,060 recorded actions. A missed
    rename is silent: the executor rejects the unknown kind and a replayable run
    reports as unreplayable."""
    action = backfill.to_action({"action_kind": kind, "action_args": args})
    assert action is not None
    assert action["kind"] == expected_kind
    assert action["args"] == expected_args


def test_a_coordinate_action_is_refused_rather_than_translated():
    assert backfill.to_action({"action_kind": "click_xy", "action_args": {"x": 10, "y": 20}}) is None


# --------------------------------------------------------------------------- persistence
def _replayed(effects=None, absent=None, steps=None, accept=backfill.WORLD):
    run = archived(steps or [
        click("btn-a", world=world_at(0, [])),
        click("btn-refund", world=world_at(1, ["ORD-1"])),
    ])
    recon, _, _ = replay(run, effects=effects or {"btn-refund": ["ORD-1"]}, absent=absent, accept=accept)
    return recon


def _checkpoint_count(db) -> int:
    return int(db.scalar(select(func.count(models.EnvironmentCheckpoint.id))))


def test_a_backfilled_run_is_imported_as_a_forkable_canonical_run(db_session):
    """The point of the exercise: after the backfill, canonical resolution finds a
    run with a world trail, which is what fork-before-step-N restores from."""
    report = backfill.apply(db_session, _replayed())
    db_session.commit()

    task = db_session.scalar(select(models.Task).where(models.Task.external_id == TASK))
    traj = canonical.for_task(db_session, task.id)
    assert report.imported and str(traj.id) == report.trajectory_id
    evidence = canonical.world_evidence(db_session, traj)
    assert evidence == {"steps": 2, "worldSteps": 2, "trail": 2}


def test_each_step_chains_to_the_checkpoint_the_previous_step_produced(db_session):
    """A fork before step N restores step N-1's "after". Chaining is the whole
    contract; an off-by-one here replays from the wrong world silently."""
    backfill.apply(db_session, _replayed())
    db_session.commit()

    steps = db_session.scalars(
        select(models.TrajectoryStep).order_by(models.TrajectoryStep.idx)
    ).all()
    assert steps[1].before_checkpoint_id == steps[0].after_checkpoint_id
    seed_cp = db_session.get(models.EnvironmentCheckpoint, steps[0].before_checkpoint_id)
    assert seed_cp.world_hash == checkpoints.hash_world(world_at(0, [])), "step 0 forks from the seed world"
    assert seed_cp.step_clock == 0


def test_an_unverified_step_breaks_the_chain_instead_of_carrying_a_stale_world(db_session):
    """The deliberate departure from _persist_gym_review's `prev or last` carry.
    Handing step N+1 the checkpoint from before step N-1 would let a fork restore
    a world two actions stale and call it a clean start."""
    recon = _replayed(effects={"btn-refund": ["ORD-WRONG"]}, steps=[
        click("btn-a", world=world_at(0, [])),
        click("btn-refund", world=world_at(1, ["ORD-1"])),   # replay produces ORD-WRONG
        click("btn-c", world=world_at(2, ["ORD-WRONG"])),
    ])
    backfill.apply(db_session, recon)
    db_session.commit()

    steps = db_session.scalars(select(models.TrajectoryStep).order_by(models.TrajectoryStep.idx)).all()
    assert steps[1].after_checkpoint_id is None, "the disputed step gets no checkpoint at all"
    assert steps[2].before_checkpoint_id is None, "and the step after it does not inherit a stale one"
    assert steps[2].after_checkpoint_id is not None, "a later verified step still recovers its own world"


def test_the_step_that_could_not_be_reproduced_can_still_be_forked_before(db_session):
    """The most valuable fork of all: an annotator rejects a step and branches
    before it. The state before it is the state AFTER its predecessor, which was
    verified independently — refusing that restore point would make the disputed
    step the one place a correction cannot start."""
    recon = _replayed(effects={"btn-refund": ["ORD-WRONG"]})
    backfill.apply(db_session, recon)
    db_session.commit()

    steps = db_session.scalars(select(models.TrajectoryStep).order_by(models.TrajectoryStep.idx)).all()
    assert steps[1].after_checkpoint_id is None, "its own world was never verified"
    assert steps[1].before_checkpoint_id == steps[0].after_checkpoint_id


def test_a_world_that_could_not_be_verified_is_never_written(db_session):
    """Stated as the negative, because this is the failure the module exists to
    prevent: the wrong world must not reach the database by ANY path."""
    recon = _replayed(effects={"btn-refund": ["ORD-WRONG"]})
    backfill.apply(db_session, recon)
    db_session.commit()

    wrong = checkpoints.hash_world(world_at(1, ["ORD-WRONG"]))
    hashes = db_session.scalars(select(models.EnvironmentCheckpoint.world_hash)).all()
    assert wrong not in hashes
    disputed = db_session.scalars(select(models.TrajectoryStep).order_by(models.TrajectoryStep.idx)).all()[1]
    assert disputed.world_after is None
    assert disputed.after_checkpoint_id is None
    # The trail keeps what the ARCHIVE recorded for this step. That is first-hand
    # evidence and stays; what must never appear anywhere is the replay's version.
    assert disputed.trajectory.raw["gymResume"]["worldTrail"][1] == world_at(1, ["ORD-1"])


def test_a_run_with_nothing_verifiable_writes_nothing_at_all(db_session):
    recon = _replayed(steps=[click("btn-a", world=world_at(0, ["NEVER"]))])
    report = backfill.apply(db_session, recon)
    db_session.commit()
    assert report.refused
    assert _checkpoint_count(db_session) == 0
    assert db_session.scalar(select(func.count(models.Trajectory.id))) == 0


def test_a_refused_reconstruction_is_never_persisted(db_session):
    run = archived([click("a", world=world_at(0, []))])
    gym = FakeGym()
    gym.reachable = False
    recon = backfill.reconstruct(run, gym, FakeExecutor(gym))
    report = backfill.apply(db_session, recon)
    assert report.refused and _checkpoint_count(db_session) == 0


# --------------------------------------------------------------------------- idempotency
def test_running_the_backfill_twice_writes_the_same_row_set(db_session):
    """Operators re-run this: a batch dies halfway, the archive grows, coverage is
    re-measured. A second pass must not duplicate checkpoints or mint a second
    trajectory that then competes to be canonical."""
    backfill.apply(db_session, _replayed())
    db_session.commit()
    before = (_checkpoint_count(db_session), db_session.scalar(select(func.count(models.Trajectory.id))))

    second = backfill.apply(db_session, _replayed())
    db_session.commit()

    after = (_checkpoint_count(db_session), db_session.scalar(select(func.count(models.Trajectory.id))))
    assert after == before
    assert second.imported is False, "the second pass recognized its own import"
    assert second.checkpoints_written == 0 and second.checkpoints_reused == 3


def test_a_second_pass_keeps_the_chain_it_wrote_the_first_time(db_session):
    backfill.apply(db_session, _replayed())
    db_session.commit()
    backfill.apply(db_session, _replayed())
    db_session.commit()

    steps = db_session.scalars(select(models.TrajectoryStep).order_by(models.TrajectoryStep.idx)).all()
    assert steps[1].before_checkpoint_id == steps[0].after_checkpoint_id
    assert all(s.after_checkpoint_id is not None for s in steps)


def test_a_checkpoint_that_disagrees_with_a_fresh_replay_is_reported_not_overwritten(db_session):
    """A disagreement means the environment moved. The first-hand record is older
    evidence than a replay and must survive it — loudly, as a conflict count."""
    backfill.apply(db_session, _replayed())
    db_session.commit()
    original = [c.world_hash for c in db_session.scalars(
        select(models.EnvironmentCheckpoint).order_by(models.EnvironmentCheckpoint.step_clock)
    ).all()]

    drifted = _replayed(effects={"btn-refund": ["ORD-1", "ORD-EXTRA"]}, steps=[
        click("btn-a", world=world_at(0, [])),
        click("btn-refund", world=world_at(1, ["ORD-1", "ORD-EXTRA"])),
    ])
    report = backfill.apply(db_session, drifted)
    db_session.commit()

    assert report.conflicts == 1
    now = [c.world_hash for c in db_session.scalars(
        select(models.EnvironmentCheckpoint).order_by(models.EnvironmentCheckpoint.step_clock)
    ).all()]
    assert now == original


# --------------------------------------------------------------------------- archive reading
def test_the_task_id_is_read_from_the_filename_without_parsing_the_file():
    """Indexing 4,683 files must not mean loading every world snapshot ever
    recorded into memory."""
    assert backfill.task_of(Path("M40_bogus_pricematch__0__35e9b2bc.jsonl")) == "M40/bogus_pricematch"
    assert backfill.task_of(Path("A1_buy_wireless_mouse__0__f20fddcf.jsonl")) == "A1/buy_wireless_mouse"


def test_a_fully_replayable_episode_is_preferred_over_a_longer_partial_one(tmp_path):
    """A mark-addressed action in the middle costs every world after it, so more
    steps is not more trail."""
    long_partial = archived([click("a"), click("b"), {"action_kind": "click_xy", "action_args": {"x": 1, "y": 2}}])
    short_clean = archived([click("a"), click("b")])
    (tmp_path / "M40_bogus_pricematch__0__long.jsonl").write_text(json.dumps(long_partial.payload))
    (tmp_path / "M40_bogus_pricematch__0__short.jsonl").write_text(json.dumps(short_clean.payload))

    chosen = backfill.pick(backfill.index(tmp_path)[TASK])
    assert chosen.path.name == "M40_bogus_pricematch__0__short.jsonl"


def test_an_episode_that_recorded_worlds_is_preferred_over_a_longer_one_that_did_not(tmp_path):
    """A recorded world is the only evidence strong enough to verify a
    reconstruction exactly; without one the replay can only be checked against
    counts. Sixteen unverifiable steps are worth less than thirteen provable ones."""
    longer = archived([click(f"btn-{i}") for i in range(4)])
    with_worlds = archived([click("a", world=world_at(0, [])), click("b", world=world_at(1, []))])
    (tmp_path / "M40_bogus_pricematch__0__longer.jsonl").write_text(json.dumps(longer.payload))
    (tmp_path / "M40_bogus_pricematch__0__worlds.jsonl").write_text(json.dumps(with_worlds.payload))

    chosen = backfill.pick(backfill.index(tmp_path)[TASK])
    assert chosen.path.name == "M40_bogus_pricematch__0__worlds.jsonl"


def test_the_recorded_start_path_is_kept_but_its_dead_origin_is_not():
    """122 archived episodes start on a port that has not existed for months. The
    PATH is what stops a first click from missing an element that only exists on
    /mail; the origin is just wherever that capture's gym happened to listen."""
    run = archived([click("a")])
    run.payload["initial_url"] = "http://localhost:8011/mail?tab=1"
    assert backfill.start_url(run, "http://localhost:8000") == "http://localhost:8000/mail?tab=1"


def test_a_run_that_recorded_no_start_url_opens_at_the_gym_root():
    run = archived([click("a")])
    run.payload["initial_url"] = ""
    assert backfill.start_url(run, "http://localhost:8000") == "http://localhost:8000/"


# --------------------------------------------------------------------------- the CLI
@pytest.fixture()
def archive_dir(tmp_path):
    run = archived([
        click("btn-a", world=world_at(0, [])),
        click("btn-refund", world=world_at(1, ["ORD-1"])),
    ])
    (tmp_path / "M40_bogus_pricematch__0__abc.jsonl").write_text(json.dumps(run.payload))
    return tmp_path


def _load_cli():
    """Import scripts/backfill_trajectories.py from its own location."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "scripts" / "backfill_trajectories.py"
    spec = importlib.util.spec_from_file_location("backfill_trajectories_cli", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def cli(_session_factory):
    """The real CLI, wired to fakes at the ONE seam it has: how it connects to a
    gym and a browser. Everything else — argument parsing, task selection, the
    dry-run default, the per-task commit — is the shipped code path."""
    import contextlib

    # Loaded by PATH, not as a package. `scripts/` is a directory of scripts, not
    # an installed module, so `from scripts import ...` only resolves when pytest
    # happens to be run from backend/ — the suite passed there and errored from
    # the repo root, which is where CI runs it.
    cli_mod = _load_cli()

    def connect(args):
        gym = FakeGym()

        @contextlib.contextmanager
        def executor(initial_url):
            assert initial_url == "http://localhost:8000/market", \
                "the session must open at the run's OWN start URL, not the app root"
            yield FakeExecutor(gym, effects={"btn-refund": ["ORD-1"]})

        return gym, executor

    def run(argv):
        return cli_mod.main(argv, connect=connect, sessions=_session_factory)

    return run


def test_audit_reports_coverage_and_writes_nothing(cli, archive_dir, db_session, capsys):
    assert cli(["audit", "--archive", str(archive_dir), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"] == {
        "tasks": 1, "refused": 0, "steps": 2, "executed": 2, "accepted": 2,
        "worldEvidence": 2, "snapshotEvidence": 0,
        "tasksFullyCovered": 1, "tasksPartlyCovered": 0, "tasksUncovered": 0, "coverage": 1.0,
    }
    assert _checkpoint_count(db_session) == 0


def test_backfill_is_a_dry_run_unless_writing_is_asked_for(cli, archive_dir, db_session, capsys):
    """Writing is opt-in because this command rewrites what every annotator opening
    the task will see."""
    assert cli(["backfill", "--archive", str(archive_dir)]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert _checkpoint_count(db_session) == 0


def test_backfill_with_write_persists_the_verified_steps(cli, archive_dir, db_session, capsys):
    assert cli(["backfill", "--archive", str(archive_dir), "--write", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["writes"][0]["steps_updated"] == 2
    assert out["writes"][0]["checkpoints_written"] == 3  # seed + one per verified step
    assert _checkpoint_count(db_session) == 3


def test_a_task_filter_that_matches_nothing_replays_nothing(cli, archive_dir, capsys):
    assert cli(["audit", "--archive", str(archive_dir), "--task", "M99/not_here", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["summary"]["tasks"] == 0
