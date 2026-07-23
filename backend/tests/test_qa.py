"""Multi-annotator QA — agreement aggregation + reviewer adjudication.

Identity now comes from auth (a signed-in account per client), not a body email,
so each annotator is a separate authenticated client via `client_for`."""


def _submit(c, task, corrected):
    sid = c.post(f"/api/tasks/{task}/sessions", json={"fresh": True}).json()["sessionId"]
    vs = c.get(f"/api/tasks/{task}/review").json()["verifiers"]
    if corrected:
        c.post(f"/api/sessions/{sid}/rerun", json={"fromStep": 12, "correction": "fix", "mode": "deterministic"})
    c.patch(f"/api/sessions/{sid}", json={"reviewedThrough": 999})
    c.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    c.post(f"/api/sessions/{sid}/run", json={"corrected": corrected, "verifiers": vs, "overrides": []})
    c.post(f"/api/sessions/{sid}/submit", json={
        "reward": 1 if corrected else 0, "override": not corrected, "overrideReason": "x"})
    return sid


def test_qa_agreement_and_adjudication(client_for, reviewer_client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    ca, cb, cc = client_for("a@x.io"), client_for("b@x.io"), client_for("c@x.io")
    a = _submit(ca, "GYM-2041", True)
    _submit(cb, "GYM-2041", True)
    _submit(cc, "GYM-2041", False)  # a dissenting reward 0

    row = next(t for t in ca.get("/api/qa/tasks").json()["tasks"] if t["taskExternalId"] == "GYM-2041")
    assert row["submissions"] == 3 and row["annotators"] == 3
    assert row["majorityReward"] == 1 and row["disputed"] is True
    assert row["agreement"] == round(2 / 3, 3)

    r = reviewer_client.post("/api/qa/tasks/GYM-2041/adjudicate", json={"sessionId": a, "reviewer": "rev@x.io"})
    assert r.status_code == 200
    subs = ca.get("/api/qa/tasks/GYM-2041/submissions").json()["submissions"]
    accepted = [s for s in subs if s["accepted"]]
    assert len(accepted) == 1 and accepted[0]["sessionId"] == a


def test_agreement_is_per_distinct_annotator_not_submission_count(client_for, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    # bob is prolific: 2 sessions, both reward 0. alice: 1 session, reward 1.
    cb, ca = client_for("bob@x.io"), client_for("alice@x.io")
    _submit(cb, "GYM-2041", False)
    _submit(cb, "GYM-2041", False)
    _submit(ca, "GYM-2041", True)
    row = next(t for t in ca.get("/api/qa/tasks").json()["tasks"] if t["taskExternalId"] == "GYM-2041")
    assert row["submissions"] == 3 and row["annotators"] == 2
    # per-annotator votes = {bob:0, alice:1} → agreement 0.5; submission-weighted would be 0.667.
    assert row["agreement"] == 0.5


def test_qa_unknown_task_404(client):
    assert client.get("/api/qa/tasks/NOPE/submissions").status_code == 404
