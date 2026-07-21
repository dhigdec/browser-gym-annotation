"""The task registry (M7)."""

from app.api.tasks import _ORDER, _TASKS, list_tasks, task_fixture


def test_registry_loads_multiple_tasks():
    assert len(_ORDER) >= 3
    assert "GYM-2041" in _TASKS


def test_list_tasks_shape_carries_queue_position():
    lst = list_tasks()
    assert lst[0]["total"] == len(_ORDER)
    assert lst[0]["index"] == 0
    assert {"id", "title", "priority", "meta", "index", "total"} <= set(lst[0])


def test_task_fixture_unknown_is_none():
    assert task_fixture("NOPE-9999") is None


def test_every_task_has_a_final_state_and_checks():
    for ext in _ORDER:
        fx = task_fixture(ext)
        assert "finalState" in fx
        assert {"original", "corrected"} <= set(fx["finalState"])
        assert all("check" in v for v in fx["verifiers"])
