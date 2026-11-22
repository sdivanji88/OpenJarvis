"""Tests for SchedulerStore — SQLite CRUD for scheduled tasks and run logs."""

from __future__ import annotations

import sqlite3

import pytest

from openjarvis.scheduler.store import RunOutcome, SchedulerStore, default_store_path


@pytest.fixture()
def store(tmp_path):
    """Create a SchedulerStore backed by a temporary SQLite database."""
    s = SchedulerStore(tmp_path / "scheduler_test.db")
    yield s
    s.close()


def _make_task(task_id: str = "t1", **overrides) -> dict:
    base = {
        "id": task_id,
        "prompt": "summarize the news",
        "schedule_type": "interval",
        "schedule_value": "3600",
        "context_mode": "isolated",
        "status": "active",
        "next_run": "2026-01-01T00:00:00+00:00",
        "last_run": None,
        "agent": "simple",
        "tools": "",
        "metadata": {},
    }
    base.update(overrides)
    return base


# -- Task CRUD ---------------------------------------------------------------


class TestTaskCRUD:
    def test_save_and_get(self, store):
        task = _make_task()
        store.save_task(task)
        got = store.get_task("t1")
        assert got is not None
        assert got["id"] == "t1"
        assert got["prompt"] == "summarize the news"
        assert got["schedule_type"] == "interval"
        assert got["schedule_value"] == "3600"

    def test_get_missing_returns_none(self, store):
        assert store.get_task("nonexistent") is None

    def test_list_tasks_all(self, store):
        store.save_task(_make_task("t1"))
        store.save_task(_make_task("t2", status="paused"))
        store.save_task(_make_task("t3", status="completed"))
        all_tasks = store.list_tasks()
        assert len(all_tasks) == 3

    def test_list_tasks_filtered(self, store):
        store.save_task(_make_task("t1", status="active"))
        store.save_task(_make_task("t2", status="paused"))
        store.save_task(_make_task("t3", status="active"))
        active = store.list_tasks(status="active")
        assert len(active) == 2
        paused = store.list_tasks(status="paused")
        assert len(paused) == 1

    def test_update_task(self, store):
        task = _make_task()
        store.save_task(task)
        task["status"] = "paused"
        store.update_task(task)
        got = store.get_task("t1")
        assert got["status"] == "paused"

    def test_delete_task(self, store):
        store.save_task(_make_task())
        store.delete_task("t1")
        assert store.get_task("t1") is None

    def test_metadata_serialized_as_json(self, store):
        task = _make_task(metadata={"key": "value", "count": 42})
        store.save_task(task)
        got = store.get_task("t1")
        assert got["metadata"] == {"key": "value", "count": 42}


# -- Due tasks ---------------------------------------------------------------


class TestDueTasks:
    def test_get_due_tasks(self, store):
        store.save_task(_make_task("t1", next_run="2026-01-01T00:00:00+00:00"))
        store.save_task(_make_task("t2", next_run="2026-06-01T00:00:00+00:00"))
        store.save_task(_make_task("t3", next_run="2026-03-01T00:00:00+00:00"))
        due = store.get_due_tasks("2026-03-15T00:00:00+00:00")
        ids = {d["id"] for d in due}
        assert "t1" in ids
        assert "t3" in ids
        assert "t2" not in ids

    def test_due_tasks_excludes_paused(self, store):
        store.save_task(
            _make_task("t1", next_run="2026-01-01T00:00:00+00:00", status="paused")
        )
        due = store.get_due_tasks("2026-06-01T00:00:00+00:00")
        assert len(due) == 0

    def test_due_tasks_excludes_null_next_run(self, store):
        store.save_task(_make_task("t1", next_run=None))
        due = store.get_due_tasks("2026-06-01T00:00:00+00:00")
        assert len(due) == 0


# -- Run logs ----------------------------------------------------------------


class TestRunLogs:
    def test_log_run_and_retrieve(self, store):
        store.save_task(_make_task())
        store.log_run(
            task_id="t1",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:01:00+00:00",
            outcome=RunOutcome.SUCCESS,
            result="Done",
            error="",
        )
        logs = store.get_run_logs("t1")
        assert len(logs) == 1
        assert logs[0]["success"] == 1
        assert logs[0]["result"] == "Done"

    def test_log_run_failure(self, store):
        store.save_task(_make_task())
        store.log_run(
            task_id="t1",
            started_at="2026-01-01T00:00:00+00:00",
            finished_at="2026-01-01T00:01:00+00:00",
            outcome=RunOutcome.FAILED,
            result="",
            error="Connection timeout",
        )
        logs = store.get_run_logs("t1")
        assert len(logs) == 1
        assert logs[0]["success"] == 0
        assert logs[0]["error"] == "Connection timeout"

    def test_log_run_limit(self, store):
        store.save_task(_make_task())
        for i in range(20):
            store.log_run(
                task_id="t1",
                started_at=f"2026-01-{i + 1:02d}T00:00:00+00:00",
                finished_at=f"2026-01-{i + 1:02d}T00:01:00+00:00",
                outcome=RunOutcome.SUCCESS,
            )
        logs = store.get_run_logs("t1", limit=5)
        assert len(logs) == 5

    def test_get_run_logs_empty(self, store):
        logs = store.get_run_logs("nonexistent")
        assert logs == []

    def test_outcome_is_stored_and_derives_success(self, store):
        store.save_task(_make_task())
        store.log_run(
            "t1", "2026-01-01T00:00:00", "2026-01-01T00:00:01", RunOutcome.SUCCESS
        )
        store.log_run(
            "t1", "2026-01-02T00:00:00", "2026-01-02T00:00:01", RunOutcome.MISSED
        )

        newest, oldest = store.get_run_logs("t1")
        assert (newest["outcome"], newest["success"]) == ("missed", 0)
        assert (oldest["outcome"], oldest["success"]) == ("success", 1)

    def test_log_run_accepts_plain_outcome_string(self, store):
        store.log_run("t1", "2026-01-01T00:00:00", "2026-01-01T00:00:01", "missed")

        (log,) = store.get_run_logs("t1")
        assert (log["outcome"], log["success"]) == ("missed", 0)

    @pytest.mark.parametrize("outcome", [True, False, "bogus", ""])
    def test_log_run_rejects_non_outcome_and_writes_nothing(self, store, outcome):
        with pytest.raises(ValueError):
            store.log_run("t1", "2026-01-01T00:00:00", "x", outcome)

        assert store.get_run_logs("t1") == []

    @pytest.mark.parametrize(("success", "expected"), [(1, "success"), (0, "failed")])
    def test_row_with_empty_outcome_reads_outcome_from_success(
        self, store, tmp_path, success, expected
    ):
        conn = sqlite3.connect(tmp_path / "scheduler_test.db")
        conn.execute(
            "INSERT INTO task_run_logs (task_id, started_at, success, outcome) "
            "VALUES ('t1', '2026-01-01T00:00:00', ?, '')",
            (success,),
        )
        conn.commit()
        conn.close()

        (log,) = store.get_run_logs("t1")
        assert log["outcome"] == expected
        assert log["success"] == success


_OLD_LOGS_SCHEMA = """\
CREATE TABLE task_run_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    success     INTEGER NOT NULL DEFAULT 0,
    result      TEXT    NOT NULL DEFAULT '',
    error       TEXT    NOT NULL DEFAULT ''
);
"""


class TestOutcomeMigration:
    def test_old_database_gains_outcome_and_keeps_rows(self, tmp_path):
        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        conn.execute(_OLD_LOGS_SCHEMA)
        conn.execute(
            "INSERT INTO task_run_logs (task_id, started_at, success, error) "
            "VALUES ('t1', '2026-01-01T00:00:00', 0, 'boom')"
        )
        conn.commit()
        conn.close()

        store = SchedulerStore(db)
        try:
            store.log_run("t1", "2026-01-02T00:00:00", "x", RunOutcome.SUCCESS)
            newest, old = store.get_run_logs("t1")
        finally:
            store.close()

        assert old["error"] == "boom"
        assert old["outcome"] == "failed"
        assert newest["outcome"] == "success"

    def test_reopening_a_migrated_database_is_a_no_op(self, tmp_path):
        db = tmp_path / "s.db"
        SchedulerStore(db).close()

        SchedulerStore(db).close()

        conn = sqlite3.connect(db)
        names = [row[1] for row in conn.execute("PRAGMA table_info(task_run_logs)")]
        conn.close()
        assert names.count("outcome") == 1


# -- Claim (compare-and-set) -------------------------------------------------

_SLOT = "2026-01-01T00:00:00+00:00"
_NEXT = "2026-01-01T01:00:00+00:00"
_STARTED = "2026-01-01T00:00:05+00:00"


class TestClaimTask:
    def _claim(self, store, expected=_SLOT, next_run=_NEXT, status="active"):
        return store.claim_task(
            "t1",
            expected_next_run=expected,
            next_run=next_run,
            last_run=_STARTED,
            status=status,
        )

    def test_claim_advances_schedule(self, store):
        store.save_task(_make_task(next_run=_SLOT))

        assert self._claim(store) is True

        got = store.get_task("t1")
        assert got["next_run"] == _NEXT
        assert got["last_run"] == _STARTED
        assert got["status"] == "active"

    def test_second_claim_of_same_slot_fails(self, store):
        store.save_task(_make_task(next_run=_SLOT))

        assert self._claim(store) is True
        assert self._claim(store) is False
        assert store.get_task("t1")["next_run"] == _NEXT

    def test_stale_expected_next_run_fails(self, store):
        store.save_task(_make_task(next_run=_NEXT))

        assert self._claim(store, expected=_SLOT) is False
        assert store.get_task("t1")["last_run"] is None

    @pytest.mark.parametrize("status", ["paused", "cancelled", "completed"])
    def test_inactive_task_cannot_be_claimed(self, store, status):
        store.save_task(_make_task(next_run=_SLOT, status=status))

        assert self._claim(store) is False
        assert store.get_task("t1")["status"] == status

    def test_missing_task_cannot_be_claimed(self, store):
        assert self._claim(store) is False

    def test_null_next_run_matches_null_expected(self, store):
        store.save_task(_make_task(next_run=None))

        assert self._claim(store, expected=None) is True

    def test_null_expected_does_not_match_scheduled_task(self, store):
        store.save_task(_make_task(next_run=_SLOT))

        assert self._claim(store, expected=None) is False

    def test_claim_can_complete_one_shot_task(self, store):
        store.save_task(_make_task(next_run=_SLOT))

        assert self._claim(store, next_run=None, status="completed") is True

        got = store.get_task("t1")
        assert got["next_run"] is None
        assert got["status"] == "completed"


class TestDefaultStorePath:
    @staticmethod
    def _config(db_path: str = ""):
        from types import SimpleNamespace

        return SimpleNamespace(scheduler=SimpleNamespace(db_path=db_path))

    def test_unset_path_follows_openjarvis_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))

        assert default_store_path(self._config()) == tmp_path / "scheduler.db"

    def test_configured_path_expands_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))

        got = default_store_path(self._config("~/sched.db"))

        assert got == tmp_path / "sched.db"
