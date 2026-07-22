import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api", tags=["tasks"])

_FIX_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_SNAP_DIR = Path(__file__).resolve().parent.parent / "snapshots"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


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


def _load_breakers() -> list[dict]:
    """The curated 85-breaker set (sellable_breakers_v2). These are the primary
    review queue — each is a live gym task, reviewed by running the agent in the
    gym and loading the real trajectory."""
    f = _DATA_DIR / "breakers.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []


_BREAKERS = _load_breakers()


def task_fixture(external_id: str) -> dict | None:
    return _TASKS.get(external_id)


def _title_of(ext: str) -> str:
    leaf = ext.split("/")[-1] if "/" in ext else ext
    return leaf.replace("_", " ").strip().capitalize() or ext


def _fixture_items() -> list[dict]:
    total = len(_ORDER)
    return [
        {
            "id": _TASKS[ext]["task"]["id"],
            "title": _TASKS[ext]["task"]["title"],
            "priority": _TASKS[ext]["task"]["priority"],
            "meta": _TASKS[ext]["task"]["meta"],
            "source": "fixture",
            "index": i,
            "total": total,
        }
        for i, ext in enumerate(_ORDER)
    ]


def _breaker_items() -> list[dict]:
    total = len(_BREAKERS)
    return [
        {
            "id": b["id"],
            "title": _title_of(b["id"]),
            "priority": b.get("priority", "High"),
            "meta": b.get("pattern", ""),
            "prompt": b.get("prompt", ""),
            "source": "gym",  # loaded via a live gym run, not a baked fixture
            "index": i,
            "total": total,
        }
        for i, b in enumerate(_BREAKERS)
    ]


@router.get("/tasks")
def list_tasks(set: str = Query("breakers", pattern="^(breakers|fixtures|all)$")) -> list[dict]:
    """The review queue. Default = the 85 curated breakers (the real work);
    `?set=fixtures` = the hand-authored demo fixtures; `?set=all` = both."""
    if set == "fixtures":
        return _fixture_items()
    if set == "all":
        items = _fixture_items() + _breaker_items()
        for i, it in enumerate(items):
            it["index"], it["total"] = i, len(items)
        return items
    # default: the breakers, falling back to fixtures if the manifest is missing.
    return _breaker_items() or _fixture_items()


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
