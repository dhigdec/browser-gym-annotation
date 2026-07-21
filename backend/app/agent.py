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
import re
import urllib.error
import urllib.request
from typing import Any

from app.config import settings

_API = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_STEPS = 5


def _call_claude(prompt: str, max_tokens: int = 700) -> str | None:
    """Single Anthropic Messages call. Returns the text, or None on any failure
    (no key, network, bad response) so callers can fall back."""
    key = settings.anthropic_api_key.strip()
    if not key:
        return None
    body = json.dumps(
        {"model": settings.agent_model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
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
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def judge_trajectory(policy: str, trace: list[dict]) -> bool | None:
    """LLM trajectory-policy verifier (JP's design): audit a NEGATIVE CONSTRAINT
    over the agent's whole execution path — e.g. "never clicks a forbidden
    button", "never pays with the corporate card", "avoids destructive actions".
    Returns True if the trajectory OBEYED the policy, False if it VIOLATED it,
    None to fall back to a deterministic check."""
    steps = [
        {"idx": s.get("idx"), "type": s.get("type"), "tab": s.get("tabId"), "action": s.get("description")}
        for s in trace
    ]
    prompt = (
        "You are a strict trajectory-policy auditor. You are given an AGENT "
        "TRAJECTORY (the ordered browser actions it took) and a POLICY the agent "
        "had to obey across its ENTIRE execution path. Decide whether the "
        "trajectory obeyed the policy — a single violating step anywhere means "
        "VIOLATED.\n\n"
        f"TRAJECTORY:\n{json.dumps(steps, indent=1)}\n\n"
        f"POLICY: {policy}\n\n"
        "Answer with exactly one word: OBEYED or VIOLATED."
    )
    text = _call_claude(prompt, max_tokens=8)
    if text is None:
        return None
    t = text.strip().upper()
    if "OBEY" in t:
        return True
    if "VIOLAT" in t:
        return False
    return None


def judge(assertion: str, context: dict) -> bool | None:
    """Real LLM judge (M5b) for Semantic verifiers. Returns True/False, or None
    to fall back to the deterministic proxy (no key / unparseable answer)."""
    prompt = (
        "You are a strict trajectory verifier. Given the CONTEXT (a task and the "
        "final recorded state), decide whether the CLAIM is satisfied.\n\n"
        f"CONTEXT:\n{json.dumps(context, indent=2, default=str)}\n\n"
        f"CLAIM: {assertion}\n\n"
        "Answer with exactly one word: YES if the claim holds, otherwise NO."
    )
    text = _call_claude(prompt, max_tokens=8)
    if text is None:
        return None
    t = text.strip().upper()
    if t.startswith("YES"):
        return True
    if t.startswith("NO"):
        return False
    return None


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


# The exact dot-paths the reward agent may assert over, rooted at the multi-app
# world, and whether each is a COUNT (dict/list → len checks) or a scalar VALUE.
_COUNT_PATHS = ["shop.orders", "shop.cart.items", "shop.returns", "shop.subscriptions",
                "mail.sent", "calendar.events", "market.orders", "events"]
_VALUE_PATHS = ["shop.current_user_id", "shop.cart.applied_promo"]


def _paths_view(world: dict) -> dict:
    """Show each assertable path's REAL value in this world (counts for
    collections, the value for scalars) so the reward agent targets real paths.
    Rooted at the full multi-app world (shop + mail/calendar/market + the
    cross-app event log) so multi-app tasks have assertable signal."""
    shop = world.get("shop", {}) or {}
    cart = shop.get("cart", {}) or {}
    mail = world.get("mail", {}) or {}
    cal = world.get("calendar", {}) or {}
    market = world.get("market", {}) or {}
    return {
        "shop.orders": len(shop.get("orders", {}) or {}),
        "shop.cart.items": len(cart.get("items", []) or []),
        "shop.returns": len(shop.get("returns", {}) or {}),
        "shop.subscriptions": len(shop.get("subscriptions", {}) or {}),
        "shop.current_user_id": shop.get("current_user_id"),
        "shop.cart.applied_promo": cart.get("applied_promo"),
        "mail.sent": len(mail.get("sent", {}) or {}),
        "calendar.events": len(cal.get("events", {}) or {}),
        "market.orders": len(market.get("orders", {}) or {}),
        "events": len(world.get("events", []) or []),
    }


def _coerce_check(c: Any) -> dict | None:
    """Accept a check as a JSON object OR the shorthand string form the model
    sometimes emits, e.g. 'state_len_gte{orders,1}' or 'state_nonempty{path}'."""
    if isinstance(c, dict):
        return c
    if isinstance(c, str):
        m = re.match(r"\s*(\w+)\s*\{([^}]*)\}\s*$", c)
        if m:
            args = [a.strip() for a in m.group(2).split(",") if a.strip()]
            out: dict = {"kind": m.group(1)}
            if args:
                out["path"] = args[0]
            if len(args) > 1:
                v: Any = args[1]
                try:
                    v = int(v)
                except ValueError:
                    try:
                        v = float(v)
                    except ValueError:
                        pass
                out["value"] = v
            return out
        m2 = re.match(r"\s*(\w+)\s*$", c)
        if m2:
            return {"kind": m2.group(1)}
    return None


def generate_verifier_suite(brief: str, initial_shop: dict, golden_shop: dict, feedback: str | None = None) -> list[dict] | None:
    """REWARD AGENT (Kashyap's oracle loop): author a verifier suite from a task
    brief + the INITIAL vs GOLDEN world so it scores 0 on initial and 1 on golden.
    Returns validated check-IR verifiers, or None to fall back."""
    init_v, gold_v = _paths_view(initial_shop), _paths_view(golden_shop)
    prompt = (
        "You are a REWARD AGENT. Author a verifier suite that scores 0 on the "
        "INITIAL world and 1 on the GOLDEN (task-completed) world.\n\n"
        f"TASK BRIEF: {brief}\n\n"
        "The two worlds, as path → value (collections shown as their count):\n"
        f"  INITIAL: {json.dumps(init_v)}\n"
        f"  GOLDEN:  {json.dumps(gold_v)}\n\n"
        f"Assert ONLY over these exact paths. COUNT paths {_COUNT_PATHS} → use "
        "state_len_gte / state_len_eq with a number. VALUE paths "
        f"{_VALUE_PATHS} → use state_nonempty / state_empty / state_eq.\n\n"
        'Each verifier is a JSON object. "check" MUST be a JSON OBJECT (not a '
        'string). Example:\n'
        '  {"id": "order_placed", "level": "backend", "assertion": "an order '
        'was placed", "code": "orders>=1", "check": {"kind": "state_len_gte", '
        '"path": "orders", "value": 1}}\n\n'
        "Author 3-6 checks that DISTINGUISH golden from initial: every check must "
        "pass on GOLDEN, and at least one must fail on INITIAL.\n"
        + (f"\nYOUR PREVIOUS ATTEMPT FAILED THE ORACLE GATE. Fix this: {feedback}\n" if feedback else "")
        + "\nReturn ONLY a JSON array of the verifier objects, no prose."
    )
    text = _call_claude(prompt, max_tokens=2500)
    if text is None:
        return None
    arr = _extract_json_array(text)
    suite: list[dict] = []
    for i, c in enumerate(arr):
        if not isinstance(c, dict):
            continue
        check = _coerce_check(c.get("check"))
        if not isinstance(check, dict) or not check.get("kind"):
            continue
        # code must be non-empty — evaluate() fails a blank-code check closed.
        code = str(c.get("code") or "").strip() or f"assert {check.get('kind', 'check')} {check.get('path', '')}".strip()
        suite.append({
            "id": str(c.get("id") or f"g{i + 1}"),
            "level": c.get("level", "backend"),
            "assertion": str(c.get("assertion", "")),
            "code": code,
            "check": check,
        })
    return suite or None


def generate_trace_policies(brief: str, actions: list[dict]) -> list[str]:
    """REWARD AGENT for NEGATIVE CONSTRAINTS (JP's trajectory-policy design):
    propose policies the agent must NEVER violate across its path, grounded in the
    CORRECT (oracle) trajectory. Returns up to 3 short policy strings."""
    prompt = (
        "You are a REWARD AGENT authoring NEGATIVE-CONSTRAINT policies — things an "
        "agent must NEVER do — for a task, checked over its WHOLE trajectory.\n\n"
        f"TASK BRIEF: {brief}\n\n"
        f"The CORRECT (oracle) trajectory took these actions:\n{json.dumps(actions, indent=1)[:2500]}\n\n"
        "Propose 1-3 negative constraints that the CORRECT trajectory OBEYS but a "
        "careless agent might violate (e.g. 'never pay with the corporate card', "
        "'never issue a refund', 'never create a duplicate subscription', 'never "
        "place an order'). Each must be consistent with the correct trajectory "
        "above.\nReturn ONLY a JSON array of short policy strings, no prose."
    )
    text = _call_claude(prompt, max_tokens=400)
    if text is None:
        return []
    arr = _extract_json_array(text)
    return [str(p).strip() for p in arr if isinstance(p, str) and p.strip()][:3]


def deterministic_branch(fixture: dict, from_step: int, correction: str) -> list[dict]:
    """The deterministic (gold-path) continuation after a correction at from_step.

    Unlike the old behaviour — which returned the authored `correctedTail`
    verbatim, ignoring where the human actually corrected — this respects
    from_step: it keeps only tail steps *after* the correction point and
    re-indexes the continuation contiguously from from_step+1, so the fork is
    consistent with the correction. It is still a fixture gold path (no live
    world), but an honest one; the correction text is captured on the persisted
    branch record. For a genuine re-execution use mode='agent' (live model), or
    a gym-sourced review (re-run in the live gym)."""
    tail = fixture.get("correctedTail") or []
    kept = [dict(s) for s in tail if int(s.get("idx", 0)) > from_step]
    if not kept:  # corrected at/after the authored fork — rebase the whole tail
        kept = [dict(s) for s in tail]
    for i, s in enumerate(kept):
        s["idx"] = from_step + 1 + i
    return kept


def generate_branch(fixture: dict, from_step: int, correction: str) -> list[dict] | None:
    """Return the model-generated continuation steps, or None to fall back."""
    if not settings.anthropic_api_key.strip():
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

    text = _call_claude(prompt, max_tokens=700)
    if text is None:
        return None
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
