import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api", tags=["tasks"])

_FIX_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_SNAP_DIR = Path(__file__).resolve().parent.parent / "snapshots"


def _load_tasks() -> dict[str, dict]:
    """Task registry (M7). The primary review fixture plus any task in
    fixtures/tasks/. Each mirrors the frontend contract; the shape is identical
    so the queue just swaps which task is loaded."""
    tasks: dict[str, dict] = {}
    files = [_FIX_DIR / "task_review.json"]
    tasks_dir = _FIX_DIR / "tasks"
    if tasks_dir.exists():
        files += sorted(tasks_dir.glob("*.json"))
    for f in files:
        d = json.loads(f.read_text())
        tasks[d["task"]["id"]] = d
    return tasks


_TASKS = _load_tasks()
_ORDER = list(_TASKS.keys())  # primary first, then fixtures/tasks/ alphabetically
# Back-compat: the primary fixture, used as the default where a task isn't resolved.
_FIXTURE = _TASKS[_ORDER[0]]


def task_fixture(external_id: str) -> dict | None:
    return _TASKS.get(external_id)


@router.get("/tasks")
def list_tasks() -> list[dict]:
    total = len(_ORDER)
    return [
        {
            "id": _TASKS[ext]["task"]["id"],
            "title": _TASKS[ext]["task"]["title"],
            "priority": _TASKS[ext]["task"]["priority"],
            "meta": _TASKS[ext]["task"]["meta"],
            "index": i,
            "total": total,
        }
        for i, ext in enumerate(_ORDER)
    ]


@router.get("/tasks/{external_id}/review")
def get_review(external_id: str) -> dict:
    fx = _TASKS.get(external_id)
    if fx is None:
        raise HTTPException(status_code=404, detail="task not found")
    return fx


@router.get("/snapshots/{key}", response_class=HTMLResponse)
def snapshot(key: str) -> HTMLResponse:
    """Serve a captured self-contained page snapshot for the replay pane."""
    if not key.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="bad key")
    f = _SNAP_DIR / f"{key}.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="snapshot not found")
    return HTMLResponse(f.read_text(encoding="utf-8"))
