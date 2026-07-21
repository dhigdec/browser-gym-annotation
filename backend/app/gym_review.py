"""Map a real gym trajectory + its milestone verdict into the annotator's review
payload (M8), so any of the gym's real tasks can be reviewed in the Task Review
UI — real brief, real steps with real per-step screenshots, real milestones as
the verifier suite.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_TYPE = {
    "navigate": "navigate", "goto": "navigate", "open": "navigate", "open_url": "navigate",
    "fill": "type", "type": "type", "press": "type",
    "click": "click", "select": "click", "check": "click",
    "submit": "submit",
    "extract": "extract", "read": "extract",
    "open_tab": "tab", "switch_tab": "tab", "new_tab": "tab",
}


def _atype(kind: str | None) -> str:
    return _TYPE.get((kind or "").lower(), "click")


def _level(m: dict) -> str:
    n = (m.get("name") or "").lower()
    if m.get("forbidden"):
        return "safety"
    if any(w in n for w in ("cart", "order", "checkout", "address", "payment", "refund", "sub", "promo", "email", "sent", "price")):
        return "backend"
    if any(w in n for w in ("page", "view", "on_", "confirm", "render", "visible", "shown", "displayed")):
        return "ui"
    if any(w in n for w in ("judge", "correct", "intent", "match")):
        return "semantic"
    return "process"


def _milestone_result(m: dict) -> str:
    fired = (m.get("fired_at_step", -1) or -1) >= 0
    passed = (not fired) if m.get("forbidden") else fired
    return "pass" if passed else "fail"


def _humanize(s: dict) -> str:
    if (s.get("reasoning") or "").strip():
        return s["reasoning"].strip()[:120]
    kind = (s.get("action_kind") or "step").lower()
    args = s.get("action_args")
    hint = ""
    if isinstance(args, dict):
        for k in ("value", "text", "url", "path", "href", "query", "label", "selector"):
            if args.get(k):
                hint = str(args[k])[:54]
                break
    elif args:
        mm = re.search(r"['\"]([^'\"]{2,54})['\"]", str(args))
        if mm:
            hint = mm.group(1)
    verb = {"navigate": "Navigated to", "goto": "Navigated to", "open_url": "Opened",
            "fill": "Filled", "type": "Typed", "click": "Clicked", "submit": "Submitted",
            "extract": "Read", "read": "Read", "press": "Pressed"}.get(kind, kind.capitalize())
    return (f"{verb} {hint}".strip()) or kind


def to_review(run: dict, task_id: str, agent: str) -> dict:
    t = run.get("trajectory") or {}
    steps_in = t.get("steps") or []
    vr = t.get("verifier_result") or {}
    host = urlparse(t.get("initial_url") or "http://localhost:8000").netloc or "gym.local"
    tab = {"id": "gym", "app": "shop", "title": (t.get("task_category") or "Browser-Use Gym"), "host": host}

    steps = []
    for i, s in enumerate(steps_in):
        sp = s.get("screenshot_path")
        err = bool(s.get("action_error") and str(s.get("action_error")) != "None")
        steps.append({
            "idx": i + 1,
            "type": "error" if err else _atype(s.get("action_kind")),
            "tabId": "gym",
            "description": _humanize(s),
            "image": f"/api/gym/screenshot?path={sp}" if sp else None,
            "errorMsg": str(s.get("action_error")) if err else None,
            "url": s.get("url_after") or "",
        })

    verifiers = []
    for j, m in enumerate(vr.get("all_milestones") or []):
        name = m.get("name") or f"milestone_{j}"
        verifiers.append({
            "id": f"m{j}",
            "level": _level(m),
            "assertion": name.replace("_", " ").strip().capitalize(),
            "code": (
                f"milestone: {name} · weight {m.get('weight')}"
                + (" · required" if m.get("required") else "")
                + (" · forbidden" if m.get("forbidden") else "")
            ),
            "gymResult": _milestone_result(m),
        })

    diff = (t.get("task_difficulty") or "medium").lower()
    priority = {"easy": "Low", "medium": "Medium", "hard": "High"}.get(diff, "Medium")
    title = task_id.split("/")[-1].replace("_", " ").strip().capitalize()
    reward = 1 if vr.get("success") else 0
    errors = sum(1 for s in steps if s["type"] == "error")

    return {
        "task": {
            "id": task_id, "priority": priority, "title": title,
            "meta": f"{t.get('task_category', 'gym')} · {agent}",
            "prompt": t.get("task_brief") or "",
            "startState": {"summary": f"Gym task · {agent} run · seed {run.get('seed', 0)}", "url": t.get("initial_url") or ""},
            "constraints": [c for c in (diff.capitalize(), t.get("task_category")) if c],
            "allowedSites": [{"host": host, "app": "shop"}],
            "runSummary": [
                {"value": str(len(steps)), "label": "Steps"},
                {"value": "1", "label": "Tabs opened"},
                {"value": str(errors), "label": "Errors", "tone": "error" if errors else "default"},
                {"value": f"{vr.get('score', 0):.2f}", "label": "Score", "tone": "success" if reward else "error"},
            ],
        },
        "tabs": [tab],
        "steps": steps,
        "correctionSeed": "Correct the outcome, then re-verify in the live gym. Optional state edits, one per line — e.g.  shop.orders.ORD_1.payment_id = pm_personal  (or  shop.orders = {}  to void it).",
        "correctedTail": [],
        "verifiers": verifiers,
        "gymReward": reward,
        "source": "gym",
        # Everything needed to resume this episode from a corrected state (the
        # live world is attached by the run-review job as gymResume.worldState).
        "gymResume": {
            "seed": int(run.get("seed", 0)),
            "urlTrail": [s.get("url_after") or "" for s in steps_in],
            "finalUrl": t.get("final_url") or "",
        },
    }
