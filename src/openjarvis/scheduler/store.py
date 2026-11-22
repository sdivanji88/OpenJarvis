"""SQLite-backed persistence for scheduled tasks and run logs."""

from __future__ import annotations

import json
import sqlite3
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class RunOutcome(str, Enum):
    """What happened to one scheduled run; the value is the stored run-log text."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    MISSED = "missed"

    # Python 3.11+ format() would otherwise give 'RunOutcome.SUCCESS'.
    def __str__(self) -> str:
        return self.value


_CREATE_TASKS_TABLE = """\
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id              TEXT PRIMARY KEY,
    prompt          TEXT    NOT NULL,
    schedule_type   TEXT    NOT NULL,
    schedule_value  TEXT    NOT NULL,
    context_mode    TEXT    NOT NULL DEFAULT 'isolated',
    status          TEXT    NOT NULL DEFAULT 'active',
    next_run        TEXT,
    last_run        TEXT,
    agent           TEXT    NOT NULL DEFAULT 'simple',
    tools           TEXT    NOT NULL DEFAULT '',
    metadata        TEXT    NOT NULL DEFAULT '{}'
);
"""

_CREATE_LOGS_TABLE = """\
CREATE TABLE IF NOT EXISTS task_run_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    started_at  TEXT    NOT NULL,
    finished_at TEXT,
    success     INTEGER NOT NULL DEFAULT 0,
    result      TEXT    NOT NULL DEFAULT '',
    error       TEXT    NOT NULL DEFAULT '',
    outcome     TEXT    NOT NULL DEFAULT ''
);
"""

# Databases created before ``outcome`` existed keep their rows; those store ''
# and read back with an outcome derived from ``success``.
_ADD_OUTCOME_COLUMN = (
    "ALTER TABLE task_run_logs ADD COLUMN outcome TEXT NOT NULL DEFAULT ''"
)

_INSERT_TASK = """\
INSERT OR REPLACE INTO scheduled_tasks
    (id, prompt, schedule_type, schedule_value, context_mode,
     status, next_run, last_run, agent, tools, metadata)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_LOG = """\
INSERT INTO task_run_logs
    (task_id, started_at, finished_at, success, result, error, outcome)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""


class SchedulerStore:
    """SQLite CRUD store for scheduled tasks and their run logs."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_CREATE_TASKS_TABLE)
        self._conn.execute(_CREATE_LOGS_TABLE)
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(task_run_logs)")
        }
        if "outcome" not in columns:
            self._conn.execute(_ADD_OUTCOME_COLUMN)
        self._conn.commit()

    # -- Task CRUD -----------------------------------------------------------

    def save_task(self, task: Dict[str, Any]) -> None:
        """Insert or replace a scheduled task record."""
        self._conn.execute(
            _INSERT_TASK,
            (
                task["id"],
                task["prompt"],
                task["schedule_type"],
                task["schedule_value"],
                task.get("context_mode", "isolated"),
                task.get("status", "active"),
                task.get("next_run"),
                task.get("last_run"),
                task.get("agent", "simple"),
                task.get("tools", ""),
                json.dumps(task.get("metadata", {})),
            ),
        )
        self._conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single task by ID, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all tasks, optionally filtered by *status*."""
        if status is not None:
            rows = self._conn.execute(
                "SELECT * FROM scheduled_tasks WHERE status = ?", (status,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM scheduled_tasks").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_due_tasks(self, now_iso: str) -> List[Dict[str, Any]]:
        """Return active tasks whose ``next_run`` is at or before *now_iso*."""
        rows = self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE status = 'active' "
            "AND next_run IS NOT NULL AND next_run <= ?",
            (now_iso,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def claim_task(
        self,
        task_id: str,
        *,
        expected_next_run: Optional[str],
        next_run: Optional[str],
        last_run: Optional[str],
        status: str,
    ) -> bool:
        """Advance an active task's schedule only if nobody else did first.

        Returns ``True`` when this caller now owns the run for the slot
        ``expected_next_run``; ``False`` if the task was paused, cancelled, or
        already claimed (its ``next_run`` moved on).
        """
        cur = self._conn.execute(
            "UPDATE scheduled_tasks SET next_run = ?, last_run = ?, status = ? "
            "WHERE id = ? AND status = 'active' AND next_run IS ?",
            (next_run, last_run, status, task_id, expected_next_run),
        )
        self._conn.commit()
        return cur.rowcount == 1

    def update_task(self, task: Dict[str, Any]) -> None:
        """Update an existing task (same as save_task — uses INSERT OR REPLACE)."""
        self.save_task(task)

    def delete_task(self, task_id: str) -> None:
        """Delete a task by ID."""
        self._conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        self._conn.commit()

    # -- Run logs ------------------------------------------------------------

    def log_run(
        self,
        task_id: str,
        started_at: str,
        finished_at: str,
        outcome: RunOutcome | str,
        result: str = "",
        error: str = "",
    ) -> None:
        """Record a single execution of a task.

        *outcome* decides the legacy ``success`` column (1 only for
        ``RunOutcome.SUCCESS``); *error* is human-readable text only.
        """
        outcome = RunOutcome(outcome)
        self._conn.execute(
            _INSERT_LOG,
            (
                task_id,
                started_at,
                finished_at,
                int(outcome is RunOutcome.SUCCESS),
                result,
                error,
                outcome.value,
            ),
        )
        self._conn.commit()

    def get_run_logs(self, task_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Return the most recent run logs for *task_id*."""
        rows = self._conn.execute(
            "SELECT * FROM task_run_logs WHERE task_id = ? ORDER BY id DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
        return [self._log_row_to_dict(r) for r in rows]

    # -- Lifecycle -----------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # -- Helpers -------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        if "metadata" in d and isinstance(d["metadata"], str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
        return d

    @staticmethod
    def _log_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        d["outcome"] = (
            d["outcome"]
            or (RunOutcome.SUCCESS if d["success"] else RunOutcome.FAILED).value
        )
        return d


def default_store_path(config: Any = None) -> Path:
    """``scheduler.db_path`` from *config* (default: user config), else
    ``scheduler.db`` in the OpenJarvis home.

    Every writer and the daemon must resolve the same file, or tasks created
    in one place are never seen by the runner.
    """
    from openjarvis.core.config import load_config
    from openjarvis.core.paths import get_config_dir

    cfg = config if config is not None else load_config()
    configured = getattr(getattr(cfg, "scheduler", None), "db_path", "")
    if configured:
        return Path(configured).expanduser()
    return get_config_dir() / "scheduler.db"


def open_default_store(config: Any = None) -> SchedulerStore:
    """The store the scheduler daemon runs tasks from."""
    return SchedulerStore(default_store_path(config))


__all__ = ["RunOutcome", "SchedulerStore", "default_store_path", "open_default_store"]
