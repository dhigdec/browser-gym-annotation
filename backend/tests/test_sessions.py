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


# ---- start-new session, submit-once, and the trajectory record ----


def test_fresh_starts_a_new_session(client):
    sid1 = _open(client)
    resumed = client.post("/api/tasks/GYM-2041/sessions", json={}).json()["sessionId"]
    assert resumed == sid1  # default resumes the latest
    fresh = client.post("/api/tasks/GYM-2041/sessions", json={"fresh": True}).json()["sessionId"]
    assert fresh != sid1  # fresh=true starts a new one


def test_submit_locks_the_session(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    vs = _verifiers(client)
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    client.post(f"/api/sessions/{sid}/run", json={"corrected": True, "verifiers": vs, "overrides": []})
    assert client.post(f"/api/sessions/{sid}/submit", json={"reward": 1, "override": False}).status_code == 200
    # A submitted session is immutable — no superseding submission.
    assert client.post(f"/api/sessions/{sid}/submit", json={"reward": 0, "override": True, "overrideReason": "x"}).status_code == 409


def test_patch_cannot_set_submitted_or_out_of_range(client):
    sid = _open(client)
    assert client.patch(f"/api/sessions/{sid}", json={"status": "submitted"}).status_code == 400  # only /submit does that
    assert client.patch(f"/api/sessions/{sid}", json={"rerunFrom": -5}).status_code == 422


def test_submitted_session_is_immutable_via_patch_and_rerun(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    vs = _verifiers(client)
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    client.post(f"/api/sessions/{sid}/run", json={"corrected": True, "verifiers": vs, "overrides": []})
    assert client.post(f"/api/sessions/{sid}/submit", json={"reward": 1, "override": False}).status_code == 200
    # the submit lock is now enforced on BOTH reopen paths (was the blocker)
    assert client.patch(f"/api/sessions/{sid}", json={"status": "draft"}).status_code == 409
    assert client.post(f"/api/sessions/{sid}/rerun", json={"fromStep": 5, "correction": "x"}).status_code == 409


def test_rerun_rejects_out_of_range_step(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    assert client.post(f"/api/sessions/{sid}/rerun", json={"fromStep": 9999, "correction": "x"}).status_code == 422


def test_malformed_check_ir_fails_closed_not_500(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    bad = [{"id": "m", "level": "backend", "assertion": "x", "code": "c", "check": {"kind": "state_lte", "path": "p"}}]  # missing 'value'
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": bad})
    r = client.post(f"/api/sessions/{sid}/run", json={"corrected": False, "verifiers": bad, "overrides": []})
    assert r.status_code == 200                       # not a 500
    assert r.json()["results"]["m"] == "fail"         # malformed IR failed closed


def test_safety_override_flags_the_sample_and_derives_provenance(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _open(client)
    vs = _verifiers(client)
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    # original state fails the SAFETY check sa1; override it to force reward 1
    r = client.post(f"/api/sessions/{sid}/run", json={"corrected": False, "verifiers": vs, "overrides": ["sa1"]})
    assert r.json()["reward"] == 1
    sub = client.post(f"/api/sessions/{sid}/submit", json={"reward": 1, "override": False}).json()["submission"]
    assert sub["kind"] == "flagged"      # NOT a clean golden — a safety check was overridden
    assert sub["override"] is True       # provenance derived from the run, not the client flag


def test_open_session_records_a_trajectory(client, db_session):
    from app.models import Trajectory, TrajectoryStep

    sid = _open(client)
    trajs = db_session.query(Trajectory).all()
    assert len(trajs) == 1
    assert str(trajs[0].session_id) == sid
    assert db_session.query(TrajectoryStep).count() > 0  # the fixture trace is recorded
