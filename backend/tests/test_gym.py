"""The live-gym bridge (M6c) degrades cleanly when the gym isn't running."""

from app import gym_client

_DOWN = "http://127.0.0.1:59999"  # nothing listens here


def test_client_returns_none_when_gym_unreachable(monkeypatch):
    monkeypatch.setattr("app.gym_client.settings.gym_url", _DOWN)
    assert gym_client.available() is False
    assert gym_client.verify(0) is None
    assert gym_client.tasks() is None
    assert gym_client.reset("A1/x") is None


def test_status_reports_disconnected(client, monkeypatch):
    monkeypatch.setattr("app.gym_client.settings.gym_url", _DOWN)
    r = client.get("/api/gym/status")
    assert r.status_code == 200
    assert r.json()["connected"] is False


def test_verify_502_when_gym_down(client, monkeypatch):
    monkeypatch.setattr("app.gym_client.settings.gym_url", _DOWN)
    assert client.post("/api/gym/verify", json={"step": 0}).status_code == 502
    assert client.get("/api/gym/tasks").status_code == 502


def test_run_502_when_gym_down(client, monkeypatch):
    monkeypatch.setattr("app.gym_client.settings.gym_url", _DOWN)
    assert client.post("/api/gym/run", json={"taskId": "A1/x"}).status_code == 502


# ---- async run-review job queue ----


def _poll(client, jid, tries=80):
    import time

    jr = {"status": "queued"}
    for _ in range(tries):
        jr = client.get(f"/api/gym/jobs/{jid}").json()
        if jr["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    return jr


def test_run_review_is_async_and_pollable(client, monkeypatch):
    # gym returns nothing → the worker fails → job reaches a terminal 'error'.
    monkeypatch.setattr("app.gym_client.run_agent", lambda *a, **k: None)
    r = client.post("/api/gym/tasks/A1/x/run-review", json={"agent": "oracle", "seed": 0})
    assert r.status_code == 200
    assert r.json().get("jobId")  # returns a jobId immediately (run is off the request path)
    jr = _poll(client, r.json()["jobId"])
    assert jr["status"] == "error"
    assert client.get("/api/gym/jobs/does-not-exist").status_code == 404


def test_apply_edits_dot_path():
    from app.api.gym import _apply_edits

    base = {"shop": {"orders": {"o1": {"payment_id": "amex"}}}}
    out = _apply_edits(base, {"shop.orders.o1.payment_id": "personal", "shop.new": 5})
    assert out["shop"]["orders"]["o1"]["payment_id"] == "personal"
    assert out["shop"]["new"] == 5
    assert base["shop"]["orders"]["o1"]["payment_id"] == "amex"  # original untouched (deep-copied)


def test_resume_returns_real_verdict(client, monkeypatch):
    monkeypatch.setattr("app.gym_client.resume_verify", lambda *a, **k: {"score": 1.0, "success": True})
    r = client.post("/api/gym/resume", json={"taskId": "A1/x", "seed": 0, "worldState": {"shop": {}}, "urlTrail": ["/"]})
    assert r.status_code == 200
    assert r.json()["reward"] == 1 and r.json()["success"] is True


def test_resume_502_when_gym_unreachable(client, monkeypatch):
    monkeypatch.setattr("app.gym_client.resume_verify", lambda *a, **k: None)
    assert client.post("/api/gym/resume", json={"taskId": "A1/x", "seed": 0}).status_code == 502


def test_breaker_gate_rejects_non_discriminating_policy(monkeypatch):
    """The gate must KEEP a policy whose violating counterfactual is flagged, and
    REJECT one whose counterfactual is not (it doesn't actually discriminate)."""
    from app.api import gym as gymmod

    monkeypatch.setattr("app.agent.generate_trace_policies", lambda brief, actions: ["A", "B"])
    monkeypatch.setattr("app.agent.generate_policy_counterfactual", lambda pol, actions: f"__CF__ {pol}")

    def fake_judge(policy, trace):
        is_counterfactual = any("__CF__" in (s.get("description") or "") for s in trace)
        if not is_counterfactual:
            return True  # oracle OBEYS both policies
        return False if policy == "A" else True  # A's counterfactual VIOLATES; B's obeys ⇒ B doesn't discriminate

    monkeypatch.setattr("app.agent.judge_trajectory", fake_judge)

    gated = gymmod._gate_policies("brief", [{"idx": 0, "description": "did the task"}], [{"action": "click"}])
    kept = [p for p in gated if p["discriminates"]]
    assert {p["assertion"] for p in kept} == {"A"}  # B was REJECTED by the breaker gate
    assert next(p for p in gated if p["assertion"] == "B")["discriminates"] is False


def test_autogen_verifiers_is_async(client, monkeypatch):
    # gym unreachable → reward-agent job reaches a terminal error, pollable.
    monkeypatch.setattr("app.gym_client.reset", lambda *a, **k: None)
    r = client.post("/api/gym/autogen-verifiers", json={"taskId": "A1/x", "seed": 0, "iterations": 2})
    assert r.status_code == 200 and r.json().get("jobId")
    assert _poll(client, r.json()["jobId"])["status"] == "error"


def test_resume_run_is_async_and_pollable(client, monkeypatch):
    monkeypatch.setattr("app.gym_client.resume_run", lambda *a, **k: None)  # drive fails → terminal error
    r = client.post("/api/gym/resume-run", json={"taskId": "A1/x", "seed": 0, "worldState": {"shop": {}}, "resumeUrl": "/"})
    assert r.status_code == 200 and r.json().get("jobId")
    assert _poll(client, r.json()["jobId"])["status"] == "error"


def test_async_unknown_task_reports_clean_not_found_no_route_leak(client, monkeypatch):
    """D1: a gym 404 inside the async job must surface as a clean 'gym task not
    found' — not a generic 'internal error' that leaks the internal /_harness route."""
    def _raise(*a, **k):
        raise gym_client.GymTaskNotFound("/_harness/run_agent")

    monkeypatch.setattr("app.gym_client.run_agent", _raise)
    r = client.post("/api/gym/tasks/A1/nope/run-review", json={"agent": "oracle", "seed": 0})
    assert r.status_code == 200
    jr = _poll(client, r.json()["jobId"])
    assert jr["status"] == "error"
    assert jr["error"] == "gym task not found"
    assert "_harness" not in jr["error"]  # internal route no longer leaked


def test_autogen_no_suite_message_is_honest_when_key_is_set(client, monkeypatch):
    """D2: when a key IS configured but the reward agent yields no suite, the
    diagnostic must not blame a missing key."""
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "sk-present")
    monkeypatch.setattr("app.gym_client.reset", lambda *a, **k: {"start_path": "/"})
    monkeypatch.setattr("app.gym_client.world", lambda *a, **k: {"shop": {}})
    monkeypatch.setattr(
        "app.gym_client.run_agent",
        lambda *a, **k: {"trajectory": {"steps": [{"step_idx": 0, "action_kind": "click", "action_args": {}, "active_tab": "shop", "reasoning": "x"}], "task_brief": "b"}},
    )
    monkeypatch.setattr("app.agent.generate_verifier_suite", lambda *a, **k: None)
    monkeypatch.setattr("app.agent.generate_trace_policies", lambda *a, **k: [])
    r = client.post("/api/gym/autogen-verifiers", json={"taskId": "A1/x", "seed": 0, "iterations": 1})
    jr = _poll(client, r.json()["jobId"])
    assert jr["status"] == "done"
    err = jr["review"]["history"][0]["error"]
    assert "needs API key" not in err          # the old misleading blame is gone
    assert "no ANTHROPIC_API_KEY" not in err    # a key IS set → not the no-key branch
    assert "rate-limited or unavailable" in err


def test_job_store_runs_and_captures_outcomes():
    import time

    from app.jobs import JobFailure, JobStore

    st = JobStore()
    ok = st.submit("t", lambda x: x + 1, 41)
    for _ in range(80):
        if st.get(ok.id).status == "done":
            break
        time.sleep(0.02)
    assert st.get(ok.id).status == "done" and st.get(ok.id).result == 42

    def _boom():
        raise JobFailure("boom")

    bad = st.submit("t", _boom)
    for _ in range(80):
        if st.get(bad.id).status == "error":
            break
        time.sleep(0.02)
    assert st.get(bad.id).status == "error" and st.get(bad.id).error == "boom"
