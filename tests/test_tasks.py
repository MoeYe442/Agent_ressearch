import threading
import time
import pytest
from repolens.tasks import TaskService
from tests.scripted_model import ScriptedModel


def wait_task(service, task_id, terminal=True):
    for _ in range(300):
        task = service.get(task_id)
        if (task.status in {"succeeded", "partial", "failed", "cancelled"}) == terminal:
            return task
        time.sleep(0.01)
    raise AssertionError("task did not reach expected state")


def test_idempotency_conflict(indexed):
    settings, db, snapshot, _, _, _ = indexed
    service = TaskService(settings, db, ScriptedModel())
    task = service.submit(snapshot.id, "Question", "key")
    assert service.submit(snapshot.id, "Question", "key").id == task.id
    with pytest.raises(ValueError, match="idempotency_conflict"):
        service.submit(snapshot.id, "Different", "key")


def test_events_resume_after_sequence(indexed):
    settings, db, snapshot, _, _, _ = indexed
    service = TaskService(settings, db, ScriptedModel())
    service.start()
    try:
        task = service.submit(snapshot.id, "Question", None)
        assert wait_task(service, task.id).status == "succeeded"
        events = service.events(task.id, 0)
        assert [e.sequence for e in events] == list(range(1, len(events) + 1))
        assert service.events(task.id, 2) == events[2:]
        assert events[-1].type == "task_finished"
        assert service.get(task.id).usage.model_calls == 3
    finally:
        service.stop()


def test_cancel_before_next_tool(indexed):
    settings, db, snapshot, _, _, _ = indexed
    entered, release = threading.Event(), threading.Event()
    class Slow(ScriptedModel):
        def complete(self, *args, **kwargs):
            entered.set()
            assert release.wait(5)
            return super().complete(*args, **kwargs)
    service = TaskService(settings, db, Slow())
    service.start()
    try:
        task = service.submit(snapshot.id, "Question", None)
        assert entered.wait(3)
        service.cancel(task.id)
        release.set()
        assert wait_task(service, task.id).status == "cancelled"
        assert not any(e.type == "tool_started" for e in service.events(task.id, 0))
        assert service.cancel(task.id).status == "cancelled"
    finally:
        release.set()
        service.stop()


def test_restart_marks_interrupted_task_failed(indexed):
    settings, db, snapshot, _, _, _ = indexed
    service = TaskService(settings, db, None)
    task = service.submit(snapshot.id, "Question", None)
    task.status = "running"
    db.put("tasks", task.id, task)
    restarted = TaskService(settings, db, None)
    restarted.start()
    try:
        assert restarted.get(task.id).status == "failed"
        assert restarted.get(task.id).error_code == "interrupted"
    finally:
        restarted.stop()


def test_restart_requeues_old_queued_task(indexed):
    settings, db, snapshot, _, _, _ = indexed
    task = TaskService(settings, db, None).submit(snapshot.id, "Question", None)
    service = TaskService(settings, db, ScriptedModel())
    service.start()
    try:
        assert wait_task(service, task.id).status == "succeeded"
    finally:
        service.stop()
