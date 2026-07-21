"""Session lifecycle over the real API (SQLite-backed TestClient)."""


def _open(client, task="GYM-2041"):
    r = client.post(f"/api/tasks/{task}/sessions", json={})
    assert r.status_code == 200
    return r.json()["sessionId"]


def _verifiers(client, task="GYM-2041"):
    return client.get(f"/api/tasks/{task}/review").json()["verifiers"]


def test_open_session_creates_draft(client):
    body = client.post("/api/tasks/GYM-2041/sessions", json={}).json()
    assert body["status"] == "draft"
    assert body["taskExternalId"] == "GYM-2041"


def test_open_unknown_task_404(client):
    assert client.post("/api/tasks/NOPE/sessions", json={}).status_code == 404


def test_full_lifecycle_writes_a_submission(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    client.patch(f"/api/sessions/{sid}", json={"status": "steps_approved"})
    vs = _verifiers(client)
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    run = client.post(f"/api/sessions/{sid}/run", json={"corrected": True, "verifiers": vs, "overrides": []})
    assert run.json()["reward"] == 1
    sub = client.post(f"/api/sessions/{sid}/submit", json={"reward": 1, "override": False, "kind": "golden"})
    assert sub.status_code == 200
    assert sub.json()["status"] == "submitted"
    assert sub.json()["submission"]["reward"] == 1


def test_run_original_state_is_reward_zero(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    vs = _verifiers(client)
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    run = client.post(f"/api/sessions/{sid}/run", json={"corrected": False, "verifiers": vs, "overrides": []})
    assert run.json()["reward"] == 0


def test_submit_requires_reward_one_or_override(client):
    sid = _open(client)
    r = client.post(f"/api/sessions/{sid}/submit", json={"reward": 0, "override": False})
    assert r.status_code == 409


def test_rerun_falls_back_to_deterministic_without_key(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    r = client.post(f"/api/sessions/{sid}/rerun", json={"fromStep": 12, "correction": "pay paypal", "mode": "agent"})
    assert r.json()["mode"] == "deterministic"
    assert len(r.json()["steps"]) >= 1


def test_session_runs_against_its_own_task(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client, "GYM-2042")
    vs = _verifiers(client, "GYM-2042")
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    run = client.post(f"/api/sessions/{sid}/run", json={"corrected": True, "verifiers": vs, "overrides": []})
    assert run.json()["reward"] == 1


# ---- reward integrity: the server scores the PERSISTED suite, never the client ----


def test_run_ignores_client_supplied_verifiers(client, monkeypatch):
    """A fabricated trivially-passing check in the request body must NOT inflate
    the reward — the server evaluates the persisted suite (original state ⇒ 0)."""
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    vs = _verifiers(client)
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    fabricated = [{"id": "x", "level": "ui", "assertion": "always", "code": "1",
                   "check": {"kind": "trace_max_steps", "n": 9999}}]
    run = client.post(f"/api/sessions/{sid}/run",
                      json={"corrected": False, "verifiers": fabricated, "overrides": []})
    assert run.json()["reward"] == 0  # persisted suite on original state, not the bogus check


def test_run_requires_a_saved_suite(client):
    sid = _open(client)
    r = client.post(f"/api/sessions/{sid}/run", json={"corrected": True, "verifiers": [], "overrides": []})
    assert r.status_code == 409


def test_submit_stores_server_reward_not_client_asserted(client, monkeypatch):
    """Client claims reward 1 on an original-state (reward 0) run. Submit must use
    the server reward: 409 without override, and store 0 (breaker) with override."""
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    vs = _verifiers(client)
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    client.post(f"/api/sessions/{sid}/run", json={"corrected": False, "verifiers": vs, "overrides": []})
    assert client.post(f"/api/sessions/{sid}/submit", json={"reward": 1, "override": False}).status_code == 409
    sub = client.post(f"/api/sessions/{sid}/submit", json={"reward": 1, "override": True, "overrideReason": "x"})
    assert sub.status_code == 200
    assert sub.json()["submission"]["reward"] == 0  # server-computed, not the client's 1
    assert sub.json()["submission"]["kind"] == "breaker"


def test_submit_requires_a_prior_benchmark_run(client):
    sid = _open(client)
    vs = _verifiers(client)
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    r = client.post(f"/api/sessions/{sid}/submit", json={"reward": 1, "override": True, "overrideReason": "x"})
    assert r.status_code == 409  # must run the benchmark first
