"""The live-agent module — parsing + the no-key deterministic fallback."""

from app.agent import _extract_json_array, generate_branch, judge


def test_judge_without_key_returns_none(monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    assert judge("anything at all", {"x": 1}) is None


def test_generate_branch_without_key_returns_none(monkeypatch):
    monkeypatch.setattr("app.agent.settings.anthropic_api_key", "")
    fixture = {"task": {"prompt": "x"}, "tabs": [], "steps": []}
    assert generate_branch(fixture, 1, "fix it") is None


def test_extract_json_array_handles_fences_and_prose():
    assert _extract_json_array('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert _extract_json_array("here you go [1, 2, 3] done") == [1, 2, 3]
    assert _extract_json_array("no array here") == []
