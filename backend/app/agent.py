"""Live agent re-run (M6b).

Given the task, the trace up to the corrected step, and the human correction,
call a real model to generate the corrected continuation. This is genuine
agent generation from the corrected state. The generated actions are NOT yet
executed against a live gym browser (the annotator has captured snapshots, not
a live world) — verifying the true outcome of arbitrary agent actions is the
deeper gym integration (M6c). The API key is read from the environment and
never logged or persisted.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from app.config import settings

_API = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_STEPS = 5


def _extract_json_array(text: str) -> list:
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    lo, hi = text.find("["), text.rfind("]")
    if lo >= 0 and hi > lo:
        try:
            return json.loads(text[lo : hi + 1])
        except json.JSONDecodeError:
            return []
    return []


def _tab_snapshot(tab_id: str, fixture: dict) -> str | None:
    for s in reversed(fixture.get("steps", [])):
        if s.get("tabId") == tab_id and s.get("snapshot"):
            return s["snapshot"]
    return None


def generate_branch(fixture: dict, from_step: int, correction: str) -> list[dict] | None:
    """Return the model-generated continuation steps, or None to fall back."""
    key = settings.anthropic_api_key.strip()
    if not key:
        return None

    task = fixture["task"]
    tabs = fixture.get("tabs", [])
    valid_tabs = {t["id"] for t in tabs}
    trace = [s for s in fixture.get("steps", []) if s.get("idx", 0) <= from_step]

    prompt = (
        "You are a browser-use agent resuming a task after a human correction.\n\n"
        f"TASK: {task['prompt']}\n\n"
        f"TABS (id → title): {json.dumps([{'id': t['id'], 'title': t['title']} for t in tabs])}\n\n"
        f"TRACE SO FAR (steps 1..{from_step}):\n"
        + json.dumps([{"idx": s["idx"], "type": s["type"], "tabId": s["tabId"], "description": s["description"]} for s in trace])
        + f"\n\nThe run failed at step {from_step}. HUMAN CORRECTION: \"{correction}\"\n\n"
        "Generate the corrected continuation as a JSON array of 2-4 steps that complete the task "
        "following the correction. Each step is an object: "
        '{"type": one of navigate|click|type|extract|submit|tab|error, '
        '"tabId": one of the tab ids above, "description": a short past-tense action}. '
        "Return ONLY the JSON array, no prose."
    )

    body = json.dumps(
        {"model": settings.agent_model, "max_tokens": 700, "messages": [{"role": "user", "content": prompt}]}
    ).encode()
    req = urllib.request.Request(
        _API,
        data=body,
        headers={"x-api-key": key, "anthropic-version": _ANTHROPIC_VERSION, "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return None

    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    arr = _extract_json_array(text)
    steps: list[dict] = []
    for i, a in enumerate(arr[:_MAX_STEPS]):
        if not isinstance(a, dict):
            continue
        tab_id = a.get("tabId") if a.get("tabId") in valid_tabs else (tabs[0]["id"] if tabs else "")
        steps.append(
            {
                "idx": from_step + 1 + i,
                "type": a.get("type", "navigate"),
                "tabId": tab_id,
                "description": str(a.get("description", "")).strip()[:120] or "(agent step)",
                "snapshot": _tab_snapshot(tab_id, fixture),
            }
        )
    return steps or None
