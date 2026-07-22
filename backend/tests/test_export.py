"""Sample packaging / export — the deliverable golden bundle."""

import json


def _golden(client, task="GYM-2041"):
    """Drive a full annotation: broken run → correct → golden → submit."""
    sid = client.post(f"/api/tasks/{task}/sessions", json={"annotatorEmail": "e@x.io", "fresh": True}).json()["sessionId"]
    # correct the broken step → persists the golden-tail branch
    client.post(f"/api/sessions/{sid}/rerun", json={"fromStep": 12, "correction": "pay with the personal card", "mode": "deterministic"})
    vs = client.get(f"/api/tasks/{task}/review").json()["verifiers"]
    client.put(f"/api/sessions/{sid}/suite", json={"verifiers": vs})
    client.post(f"/api/sessions/{sid}/run", json={"corrected": True, "verifiers": vs, "overrides": []})
    client.post(f"/api/sessions/{sid}/submit", json={"reward": 1, "override": False})
    return sid


def test_export_sample_is_a_complete_golden_bundle(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _golden(client)
    b = client.get(f"/api/export/samples/{sid}").json()
    assert b["sample_id"] == sid
    assert b["task"]["id"] == "GYM-2041"
    assert b["reward"] == 1
    assert b["initial_state"] is not None                      # the eval triplet's initial setup
    assert b["correction"] and b["correction"]["from_step"] == 12
    assert len(b["golden_trajectory"]) > 0                      # the SFT trajectory
    assert len(b["verifiers"]) == 14                           # the verifier suite travels with it
    assert b["submission"]["reward"] == 1 and b["submission"]["kind"] == "golden"


def test_export_dataset_jsonl(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    _golden(client)
    r = client.get("/api/export/dataset.jsonl")
    assert r.status_code == 200
    assert "application/x-ndjson" in r.headers["content-type"]
    lines = [ln for ln in r.text.strip().split("\n") if ln]
    assert len(lines) >= 1
    rec = json.loads(lines[0])
    assert {"task", "initial_state", "golden_trajectory", "verifiers", "reward"} <= set(rec)


def test_list_samples_and_accepted_filter(client, monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    sid = _golden(client)
    assert client.get("/api/export/samples").json()["count"] >= 1
    # nothing accepted yet
    assert client.get("/api/export/samples?accepted=true").json()["count"] == 0
    client.post("/api/qa/tasks/GYM-2041/adjudicate", json={"sessionId": sid})
    assert client.get("/api/export/samples?accepted=true").json()["count"] == 1


def test_export_reads_the_frozen_snapshot_not_the_live_suite(client, monkeypatch, db_session):
    """Cluster A: the deliverable is frozen at submit. Even if a later suite
    version is forced into the DB directly (bypassing the API lock), the exported
    bundle must still reflect what was reviewed and scored at submit time."""
    from uuid import UUID

    from app.models import Verifier, VerifierSuite

    sid = _golden(client)
    before = client.get(f"/api/export/samples/{sid}").json()
    assert before["reward"] == 1 and len(before["verifiers"]) == 14

    # Forge a bogus 1-verifier suite straight into the DB (what the closed lock now
    # prevents over the API, but proves build_sample ignores the live latest).
    forged = VerifierSuite(session_id=UUID(sid), version=99)
    db_session.add(forged)
    db_session.flush()
    db_session.add(Verifier(suite_id=forged.id, ext_id="bogus", level="ui", assertion="trivially true", code="x", check_ir={"kind": "state_true", "path": "order.placed"}))
    db_session.commit()

    after = client.get(f"/api/export/samples/{sid}").json()
    assert after["reward"] == 1                     # unchanged — read from the snapshot
    assert len(after["verifiers"]) == 14            # not the forged single verifier
    assert not any(v["assertion"] == "trivially true" for v in after["verifiers"])
