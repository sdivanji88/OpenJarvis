"""``jarvis scheduler logs`` and ``run-task`` (F-024): outcome is a stored field."""

from __future__ import annotations

import sqlite3

import pytest
from click.testing import CliRunner

import openjarvis.system
from openjarvis.cli import scheduler_cmd
from openjarvis.cli.scheduler_cmd import scheduler
from openjarvis.core.events import EventBus, EventType
from openjarvis.scheduler.scheduler import TaskScheduler
from openjarvis.scheduler.store import RunOutcome, SchedulerStore


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "scheduler.db"
    # Commands close the store they get, so hand out a fresh one per call.
    monkeypatch.setattr(scheduler_cmd, "_get_store", lambda: SchedulerStore(path))
    return path


def _read_logs(db, task_id):
    store = SchedulerStore(db)
    try:
        return store.get_run_logs(task_id)
    finally:
        store.close()


def _create_task(db, agent="simple"):
    store = SchedulerStore(db)
    try:
        return TaskScheduler(store).create_task(
            "say hi", schedule_type="interval", schedule_value="3600", agent=agent
        )
    finally:
        store.close()


class _FakeBuilder:
    """Stands in for ``SystemBuilder``; its system replies with *reply*."""

    reply = None
    last = None

    def __init__(self, config):
        self.bus = EventBus(record_history=True)
        type(self).last = self

    def build(self):
        return self

    def ask(self, prompt, **kwargs):
        if isinstance(type(self).reply, Exception):
            raise type(self).reply
        return type(self).reply


@pytest.fixture()
def builder(monkeypatch):
    monkeypatch.setattr(openjarvis.system, "SystemBuilder", _FakeBuilder)
    return _FakeBuilder


def _invoke(*args):
    return CliRunner().invoke(scheduler, list(args), terminal_width=200)


class TestLogs:
    def test_outcome_column_shows_stored_outcome(self, db):
        store = SchedulerStore(db)
        store.log_run("t1", "2026-01-01T00:00", "x", RunOutcome.MISSED, error="late")
        store.close()

        result = _invoke("logs", "t1")

        assert result.exit_code == 0, result.output
        assert "Outcome" in result.output
        assert "missed" in result.output

    def test_legacy_rows_show_derived_outcome(self, db):
        SchedulerStore(db).close()
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO task_run_logs (task_id, started_at, success, outcome) "
            "VALUES ('t1', '2026-01-01T00:00', 1, '')"
        )
        conn.commit()
        conn.close()

        result = _invoke("logs", "t1")

        assert result.exit_code == 0, result.output
        assert "success" in result.output
        assert "yes" not in result.output


class TestRunTask:
    def test_error_result_is_logged_failed_and_exits_non_zero(self, db, builder):
        task = _create_task(db)
        builder.reply = {"content": "Unknown agent: simple", "error": True}

        result = _invoke("run-task", "simple")

        (log,) = _read_logs(db, task.id)
        assert result.exit_code == 1
        assert "Unknown agent: simple" in result.output
        assert log["success"] == 0
        assert log["outcome"] == "failed"
        assert log["error"] == "RuntimeError: Unknown agent: simple"

    def test_any_exception_is_logged_failed(self, db, builder):
        task = _create_task(db)
        builder.reply = ConnectionError("ollama down")

        result = _invoke("run-task", "simple")

        (log,) = _read_logs(db, task.id)
        assert result.exit_code == 1
        assert log["outcome"] == "failed"
        assert log["error"] == "ConnectionError: ollama down"

    def test_runs_through_the_scheduler_without_advancing_it(self, db, builder):
        task = _create_task(db)
        builder.reply = "ok"

        _invoke("run-task", "simple")

        store = SchedulerStore(db)
        next_run = store.get_task(task.id)["next_run"]
        store.close()
        types = [e.event_type for e in builder.last.bus.history]
        assert next_run == task.next_run
        assert types == [EventType.SCHEDULER_TASK_START, EventType.SCHEDULER_TASK_END]

    def test_success_logs_and_prints_reply_text(self, db, builder):
        task = _create_task(db)
        builder.reply = {"content": "hello there", "usage": {"tokens": 3}}

        result = _invoke("run-task", "simple")

        (log,) = _read_logs(db, task.id)
        assert result.exit_code == 0, result.output
        assert "hello there" in result.output
        assert "usage" not in result.output
        assert log["success"] == 1
        assert log["outcome"] == "success"
        assert log["result"] == "hello there"
