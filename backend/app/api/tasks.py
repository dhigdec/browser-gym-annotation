import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/api", tags=["tasks"])

_SNAP_DIR = Path(__file__).resolve().parent.parent / "snapshots"

# The review fixture mirrors the frontend contract. M2 replaces this with real
# trajectory data read from the gym; the shape stays the same, so the frontend
# only swaps its data source.
_FIXTURE = json.loads((Path(__file__).resolve().parent.parent / "fixtures" / "task_review.json").read_text())


@router.get("/tasks")
def list_tasks() -> list[dict]:
    task = _FIXTURE["task"]
    return [
        {
            "id": task["id"],
            "title": task["title"],
            "priority": task["priority"],
            "meta": task["meta"],
        }
    ]


@router.get("/tasks/{external_id}/review")
def get_review(external_id: str) -> dict:
    if external_id != _FIXTURE["task"]["id"]:
        raise HTTPException(status_code=404, detail="task not found")
    return _FIXTURE


@router.get("/snapshots/{key}", response_class=HTMLResponse)
def snapshot(key: str) -> HTMLResponse:
    """Serve a captured self-contained page snapshot for the replay pane."""
    if not key.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="bad key")
    f = _SNAP_DIR / f"{key}.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="snapshot not found")
    return HTMLResponse(f.read_text(encoding="utf-8"))
