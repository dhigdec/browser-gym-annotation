"""Environment checkpoints — capture and restore a COMPLETE point in time.

A checkpoint is what makes "fork before step N" and "replay the committed
sequence" real. `world_after` alone is not enough: restoring a browser also needs
the URL, the *full* tab list, cookies/storage and scroll, or a replay silently
starts from a different place than the annotator saw.

Restoration contract (§3.1 of the plan):

    1. reset the exact task revision + seed
    2. replay the accepted prefix
    3. compare hashes after every action
    4. abort on divergence
    5. loading a serialized checkpoint is an OPTIMIZATION, never the correctness story

Hashes are computed over a *normalized* world so that incidental churn (key order,
volatile counters) does not look like divergence — and so real divergence does.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app import models

# Keys that change on every read without representing task state. Hashing them
# would make every comparison diverge and the guard would be useless.
_VOLATILE_TOP = {"flash_messages", "action_log"}


def _strip_volatile(world: Any) -> Any:
    if isinstance(world, dict):
        return {k: _strip_volatile(v) for k, v in sorted(world.items()) if k not in _VOLATILE_TOP}
    if isinstance(world, list):
        return [_strip_volatile(v) for v in world]
    return world


def hash_world(world: dict | None) -> str:
    """A stable fingerprint of task-relevant world state. Empty world -> "" so a
    missing capture is never mistaken for a matching one."""
    if not world:
        return ""
    payload = json.dumps(_strip_volatile(world), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def hash_dom(dom: str | None) -> str:
    if not dom:
        return ""
    return hashlib.sha256(dom.encode()).hexdigest()


def add_artifact(db: Session, *, kind: str, uri: str, data: bytes | None = None, meta: dict | None = None) -> models.Artifact:
    """Register a blob (screenshot / DOM / AX / SoM / video). The row holds a URI +
    digest so storage can move to object storage without touching referrers."""
    art = models.Artifact(
        kind=kind,
        uri=uri,
        sha256=hashlib.sha256(data).hexdigest() if data else "",
        bytes=len(data) if data else 0,
        meta=meta or {},
    )
    db.add(art)
    db.flush()
    return art


def capture(
    db: Session,
    *,
    attempt_id: UUID | None,
    world: dict | None,
    backend_state: dict | None = None,
    browser: dict | None = None,
    step_clock: int = 0,
    environment_image_digest: str = "",
    screenshot_artifact_id: UUID | None = None,
    dom_artifact_id: UUID | None = None,
    som_artifact_id: UUID | None = None,
    dom_text: str | None = None,
) -> models.EnvironmentCheckpoint:
    """Persist a restorable point.

    `browser` carries what the gym world cannot know — url, the FULL tab list,
    cookies, storage_state, scroll, viewport, DPR. It is optional so an
    agent-only run (no live browser attached) still checkpoints its world.
    """
    b = browser or {}
    cp = models.EnvironmentCheckpoint(
        attempt_id=attempt_id,
        world=world or {},
        backend_state=backend_state or {},
        step_clock=step_clock,
        url=b.get("url", "") or "",
        active_tab=str(b.get("activeTab", "") or ""),
        tabs=b.get("tabs") or [],
        cookies=b.get("cookies") or [],
        storage_state=b.get("storageState") or {},
        local_storage=b.get("localStorage") or {},
        viewport=b.get("viewport") or {},
        device_pixel_ratio=float(b.get("devicePixelRatio") or 1.0),
        scroll=b.get("scroll") or {},
        screenshot_artifact_id=screenshot_artifact_id,
        dom_artifact_id=dom_artifact_id,
        som_artifact_id=som_artifact_id,
        world_hash=hash_world(world),
        dom_hash=hash_dom(dom_text),
        environment_image_digest=environment_image_digest,
    )
    db.add(cp)
    db.flush()
    return cp


class DivergenceError(RuntimeError):
    """Replay reached a state the checkpoint did not describe. Fail closed: a
    silently-diverged replay would produce a golden trajectory that does not
    reproduce, which is worse than no trajectory at all."""

    def __init__(self, expected: str, actual: str, at: str = ""):
        super().__init__(f"state diverged{(' at ' + at) if at else ''}: expected {expected[:12]}…, got {actual[:12]}…")
        self.expected = expected
        self.actual = actual
        self.at = at


def assert_matches(cp: models.EnvironmentCheckpoint, world: dict | None, *, at: str = "") -> None:
    """Compare live world against a checkpoint. A checkpoint with no recorded hash
    (captured before hashing, or world-less) cannot vouch for anything, so it does
    not get to claim a match."""
    if not cp.world_hash:
        return
    actual = hash_world(world)
    if actual != cp.world_hash:
        raise DivergenceError(cp.world_hash, actual, at)


def restore(cp: models.EnvironmentCheckpoint, gym, *, task_id: str, seed: int, verify: bool = True) -> bool:
    """Put a workspace back at this checkpoint.

    Uses the serialized world as the fast path, then VERIFIES by re-reading the
    world and comparing hashes — the load is an optimization, the comparison is
    what makes it trustworthy. Raises DivergenceError when the restored world is
    not the one the checkpoint recorded.
    """
    loaded = gym.load_state(task_id, seed, cp.world or {}, cp.step_clock or None)
    if loaded is None:
        return False
    if verify:
        assert_matches(cp, gym.world(), at="restore")
    return True
