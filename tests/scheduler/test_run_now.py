"""TaskScheduler.run_now — the one manual-run path (jarvis scheduler run-task)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.scheduler.policy import RunPolicy
from openjarvis.scheduler.scheduler import (
    RunOutcome,
    RunRecord,
    ScheduledTask,
    TaskScheduler,
)
from openjarvis.scheduler.store import SchedulerStore


@pytest.fixture()
def store(tmp_path):
    s = SchedulerStore(tmp_path / "scheduler.db")
    yield s
    s.close()


class _System:
    def __init__(self, reply=None, exc=None):
        self.reply = reply
        self.exc = exc
        self.calls = []

    def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.reply


def _save(store, *, agent="simple", next_run=None, metadata=None):
    next_run = next_run or (datetime.now(timezone.utc) + timedelta(hours=1))
    task = ScheduledTask(
        id="t1",
        prompt="say hi",
        schedule_type="interval",
        schedule_value="3600",
        next_run=next_run.isoformat(),
        agent=agent,
        metadata=metadata or {},
    )
    store.save_task(task.to_dict())
    return task


def test_success_is_logged_and_returned(store):
    _save(store)
    bus = EventBus(record_history=True)

    record = TaskScheduler(store, _System(reply={"content": "hi"}), bus=bus).run_now(
        "t1"
    )

    assert record == RunRecord(outcome="success", result="hi")
    (log,) = store.get_run_logs("t1")
    assert (log["outcome"], log["success"], log["result"]) == ("success", 1, "hi")
    assert [e.event_type for e in bus.history] == [
        EventType.SCHEDULER_TASK_START,
        EventType.SCHEDULER_TASK_END,
    ]


def test_exception_is_logged_as_failed(store):
    _save(store)

    record = TaskScheduler(store, _System(exc=ConnectionError("down"))).run_now("t1")

    assert record.outcome == "failed"
    assert record.error == "ConnectionError: down"
    (log,) = store.get_run_logs("t1")
    assert (log["outcome"], log["success"]) == ("failed", 0)


def test_error_dict_is_logged_as_failed(store):
    _save(store)
    system = _System(reply={"content": "Unknown agent: simple", "error": True})

    record = TaskScheduler(store, system).run_now("t1")

    assert record.outcome == "failed"
    assert "Unknown agent: simple" in record.error
    assert store.get_run_logs("t1")[0]["outcome"] == "failed"


@pytest.mark.parametrize(
    ("system_kwargs", "expected"),
    [
        ({"reply": "ok"}, RunOutcome.SUCCESS),
        ({"exc": RuntimeError("down")}, RunOutcome.FAILED),
    ],
    ids=["success", "failed"],
)
def test_returns_run_record_with_enum_outcome(store, system_kwargs, expected):
    _save(store)

    record = TaskScheduler(store, _System(**system_kwargs)).run_now("t1")

    assert isinstance(record, RunRecord)
    assert record.outcome is expected


def test_schedule_is_not_advanced(store):
    task = _save(store)

    TaskScheduler(store, _System(reply="ok")).run_now("t1")

    row = store.get_task("t1")
    assert row["next_run"] == task.next_run
    assert row["last_run"] is None
    assert row["status"] == "active"


def test_bypasses_agent_allowlist_and_misfire_window(store):
    _save(
        store,
        next_run=datetime.now(timezone.utc) - timedelta(days=1),
        metadata={"misfire_grace_minutes": 1},
    )
    system = _System(reply="ok")
    denied = RunPolicy(allowed_agents=frozenset())

    record = TaskScheduler(store, system, policy=denied).run_now("t1")

    assert record.outcome == "success"
    assert len(system.calls) == 1


def test_unknown_task_raises_key_error(store):
    with pytest.raises(KeyError):
        TaskScheduler(store, _System()).run_now("nope")
