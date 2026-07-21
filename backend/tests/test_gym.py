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
