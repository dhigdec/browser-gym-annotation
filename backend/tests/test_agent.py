"""The live-agent module — parsing + the no-key deterministic fallback."""

from app.agent import _extract_json_array, deterministic_branch, generate_branch, judge


def test_deterministic_branch_respects_from_step():
    fixture = {"correctedTail": [{"idx": 13, "type": "navigate", "description": "a"},
                                 {"idx": 14, "type": "submit", "description": "b"},
                                 {"idx": 15, "type": "tab", "description": "c"}]}
    # Correcting at the authored fork (12) keeps all three, re-indexed 13,14,15.
    at12 = deterministic_branch(fixture, 12, "fix")
    assert [s["idx"] for s in at12] == [13, 14, 15]
    # Correcting earlier (7) re-indexes the continuation contiguously from 8 —
    # NOT the old canned idx 13-15.
    at7 = deterministic_branch(fixture, 7, "fix")
    assert [s["idx"] for s in at7] == [8, 9, 10]
    # Correcting at/after the last tail step rebases the whole tail after it.
    at15 = deterministic_branch(fixture, 15, "fix")
    assert [s["idx"] for s in at15] == [16, 17, 18]


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
