"""Workspace runtime providers.

A *workspace* is one isolated gym runtime. The gym keeps a single global
``SESSION`` per process, so isolation cannot come from keying routes — it has to
come from talking to a **different process**. This module owns that lifecycle
behind an interface, so the business logic never learns about PIDs and ports and
the Kubernetes provider can drop in without touching callers.

    provision() -> health() -> endpoint() -> snapshot() -> terminate()

``LocalProcessRuntimeProvider`` spawns a gym uvicorn on an ephemeral port (dev /
single-box). ``KubernetesRuntimeProvider`` will provision a pod with the same
contract.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from app.config import settings


@dataclass(frozen=True)
class WorkspaceHandle:
    """What a provider hands back — everything needed to reach and later reclaim
    the runtime. `external_ref` is opaque to callers (a pid here, a pod name under
    Kubernetes) and is persisted on the lease so a restarted backend can reconcile."""

    endpoint: str          # http://127.0.0.1:PORT
    external_ref: str      # pid | pod name
    runtime_kind: str      # local_process | kubernetes
    image_digest: str = ""  # environment version this workspace runs


class WorkspaceRuntimeProvider(Protocol):
    """The contract every runtime must satisfy."""

    kind: str

    def provision(self, *, label: str) -> WorkspaceHandle: ...
    def health(self, handle: WorkspaceHandle) -> bool: ...
    def terminate(self, handle: WorkspaceHandle) -> None: ...


def _free_port() -> int:
    """Ask the OS for an unused port, then release it. There is an inherent race
    between releasing and binding; the caller retries on failure rather than
    pretending the reservation is atomic."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(s.getsockname()[1])


def _harness_ok(endpoint: str, timeout: float = 2.0) -> bool:
    """A gym is 'ready' only when the harness answers — not merely when the port
    accepts a connection (uvicorn binds before the app finishes importing)."""
    req = urllib.request.Request(
        endpoint.rstrip("/") + "/_harness/tasks",
        headers={"X-Harness-Token": settings.gym_harness_token},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


class LocalProcessRuntimeProvider:
    """Spawns a gym uvicorn per workspace on an ephemeral port.

    Requires ``settings.gym_repo_path`` (the gym checkout) — without it we cannot
    isolate, and the caller must fall back to the shared gym rather than silently
    letting two annotators collide.
    """

    kind = "local_process"

    def __init__(self, repo_path: str | None = None, *, boot_timeout: float = 45.0) -> None:
        self.repo_path = (repo_path or settings.gym_repo_path or "").strip()
        self.boot_timeout = boot_timeout

    @property
    def available(self) -> bool:
        return bool(self.repo_path) and os.path.isdir(self.repo_path)

    def provision(self, *, label: str) -> WorkspaceHandle:
        if not self.available:
            raise RuntimeError(
                "gym_repo_path is not configured — cannot provision an isolated workspace"
            )
        python = os.path.join(self.repo_path, ".venv", "bin", "python")
        if not os.path.exists(python):
            python = "python3"
        last_err: Exception | None = None
        for _attempt in range(3):  # the free-port lookup is inherently racy
            port = _free_port()
            env = {
                **os.environ,
                "HARNESS_TOKEN": settings.gym_harness_token,
                # Each workspace writes its own artifacts so concurrent runs never
                # read each other's newest-file-on-disk.
                "GYM_WORKSPACE_LABEL": label,
            }
            proc = subprocess.Popen(
                [python, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(port)],
                cwd=self.repo_path,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # survive a backend reload; we reclaim via the lease
            )
            endpoint = f"http://127.0.0.1:{port}"
            deadline = time.time() + self.boot_timeout
            while time.time() < deadline:
                if proc.poll() is not None:  # died during boot (port stolen, import error)
                    last_err = RuntimeError(f"gym exited during boot (rc={proc.returncode})")
                    break
                if _harness_ok(endpoint):
                    return WorkspaceHandle(
                        endpoint=endpoint,
                        external_ref=str(proc.pid),
                        runtime_kind=self.kind,
                        image_digest=settings.gym_image_digest,
                    )
                time.sleep(0.35)
            else:
                last_err = TimeoutError(f"gym did not become ready within {self.boot_timeout}s")
            with contextlib.suppress(Exception):
                proc.kill()
        raise RuntimeError(f"could not provision a workspace: {last_err}")

    def health(self, handle: WorkspaceHandle) -> bool:
        return _harness_ok(handle.endpoint)

    def terminate(self, handle: WorkspaceHandle) -> None:
        """Best-effort reclaim, but never on a pid we cannot prove is ours.

        A lease row outlives the process it names and the OS recycles pids, so a
        number stored yesterday may belong to something else entirely today. The
        reaper calls this for exactly those rows, which makes an unverified kill
        a signal sent to an arbitrary process by coincidence — and it is
        reachable from a plain `pytest` run, because the startup reconciler walks
        every lease in whatever database happens to be configured.

        So the pid must still look like the gym server this provider spawned
        before it gets a signal. When that cannot be established the process is
        LEFT ALONE: a leaked gym costs memory and is recoverable, whereas killing
        somebody else's process is not.
        """
        try:
            pid = int(handle.external_ref)
        except (TypeError, ValueError):
            return
        if pid <= 1 or not self._is_our_gym(pid):
            return
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.kill(pid, 15)  # SIGTERM

    @staticmethod
    def _is_our_gym(pid: int) -> bool:
        """Does this pid still look like a gym server we started?

        Read from the OS rather than trusted from the row, because the row is
        exactly what has gone stale. An unreadable command line answers NO — the
        entire point is to refuse when we cannot tell.
        """
        try:
            out = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        cmd = (out.stdout or "").strip()
        return "uvicorn" in cmd and "server.main:app" in cmd
