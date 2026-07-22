"""The task registry (M7)."""

from app.api.tasks import _BREAKERS, _ORDER, _TASKS, list_tasks, task_fixture


def test_registry_loads_multiple_tasks():
    assert len(_ORDER) >= 3
    assert "GYM-2041" in _TASKS


def test_default_queue_is_the_breakers():
    lst = list_tasks()  # default set = breakers
    assert len(lst) == len(_BREAKERS) == 85
    assert lst[0]["total"] == 85
    assert lst[0]["index"] == 0
    assert lst[0]["source"] == "gym"
    assert {"id", "title", "priority", "meta", "index", "total", "source"} <= set(lst[0])


def test_fixtures_queue_shape_carries_queue_position():
    lst = list_tasks("fixtures")
    assert lst[0]["total"] == len(_ORDER)
    assert lst[0]["index"] == 0
    assert lst[0]["source"] == "fixture"
    assert {"id", "title", "priority", "meta", "index", "total", "source"} <= set(lst[0])


def test_all_queue_combines_and_renumbers():
    lst = list_tasks("all")
    assert len(lst) == len(_ORDER) + len(_BREAKERS)
    assert lst[0]["total"] == len(lst)
    assert [it["index"] for it in lst[:3]] == [0, 1, 2]


def test_task_fixture_unknown_is_none():
    assert task_fixture("NOPE-9999") is None


def test_every_task_has_a_final_state_and_checks():
    for ext in _ORDER:
        fx = task_fixture(ext)
        assert "finalState" in fx
        assert {"original", "corrected"} <= set(fx["finalState"])
        assert all("check" in v for v in fx["verifiers"])
