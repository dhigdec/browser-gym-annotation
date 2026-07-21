"""Multi-annotator QA — agreement aggregation + reviewer adjudication."""


def _submit(client, task, email, corrected):
    sid = client.post(f"/api/tasks/{task}/sessions", json={"annotatorEmail": email, "fresh": True}).json()["sessionId"]
    vs = client.get(f"/api/tasks/{task}/review").json()["verifiers"]
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    client.post(f"/api/sessions/{sid}/run", json={"corrected": corrected, "verifiers": vs, "overrides": []})
    client.post(f"/api/sessions/{sid}/submit", json={
        "reward": 1 if corrected else 0, "override": not corrected, "overrideReason": "x"})
    return sid


def test_qa_agreement_and_adjudication(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    a = _submit(client, "GYM-2041", "a@x.io", True)
    _submit(client, "GYM-2041", "b@x.io", True)
    _submit(client, "GYM-2041", "c@x.io", False)  # a dissenting reward 0

    row = next(t for t in client.get("/api/qa/tasks").json()["tasks"] if t["taskExternalId"] == "GYM-2041")
    assert row["submissions"] == 3 and row["annotators"] == 3
    assert row["majorityReward"] == 1 and row["disputed"] is True
    assert row["agreement"] == round(2 / 3, 3)

    r = client.post("/api/qa/tasks/GYM-2041/adjudicate", json={"sessionId": a, "reviewer": "rev@x.io"})
    assert r.status_code == 200
    subs = client.get("/api/qa/tasks/GYM-2041/submissions").json()["submissions"]
    accepted = [s for s in subs if s["accepted"]]
    assert len(accepted) == 1 and accepted[0]["sessionId"] == a


def test_agreement_is_per_distinct_annotator_not_submission_count(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    # bob is prolific: 2 sessions, both reward 0. alice: 1 session, reward 1.
    _submit(client, "GYM-2041", "bob@x.io", False)
    _submit(client, "GYM-2041", "bob@x.io", False)
    _submit(client, "GYM-2041", "alice@x.io", True)
    row = next(t for t in client.get("/api/qa/tasks").json()["tasks"] if t["taskExternalId"] == "GYM-2041")
    assert row["submissions"] == 3 and row["annotators"] == 2
    # per-annotator votes = {bob:0, alice:1} → agreement 0.5; submission-weighted would be 0.667.
    assert row["agreement"] == 0.5


def test_qa_unknown_task_404(client):
    assert client.get("/api/qa/tasks/NOPE/submissions").status_code == 404
