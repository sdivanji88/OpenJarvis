"""Task scheduler — cron/interval/once execution with background polling."""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openjarvis.core.events import EventType
from openjarvis.scheduler.policy import RunPolicy, audit_line, missed_by
from openjarvis.scheduler.store import RunOutcome, SchedulerStore

logger = logging.getLogger(__name__)

SCHEDULER_TASK_START = EventType.SCHEDULER_TASK_START
SCHEDULER_TASK_END = EventType.SCHEDULER_TASK_END


@dataclass(slots=True)
class ScheduledTask:
    """A task scheduled for future or recurring execution."""

    id: str
    prompt: str
    schedule_type: str  # "cron" | "interval" | "once"
    schedule_value: str  # cron expression, interval seconds, ISO datetime
    context_mode: str = "isolated"
    status: str = "active"
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    agent: str = "simple"
    tools: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict for store persistence."""
        return {
            "id": self.id,
            "prompt": self.prompt,
            "schedule_type": self.schedule_type,
            "schedule_value": self.schedule_value,
            "context_mode": self.context_mode,
            "status": self.status,
            "next_run": self.next_run,
            "last_run": self.last_run,
            "agent": self.agent,
            "tools": self.tools,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ScheduledTask:
        """Deserialize from a plain dict."""
        return cls(
            id=d["id"],
            prompt=d["prompt"],
            schedule_type=d["schedule_type"],
            schedule_value=d["schedule_value"],
            context_mode=d.get("context_mode", "isolated"),
            status=d.get("status", "active"),
            next_run=d.get("next_run"),
            last_run=d.get("last_run"),
            agent=d.get("agent", "simple"),
            tools=d.get("tools", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass(frozen=True)
class RunRecord:
    """What one run produced, as written to the task's run log."""

    outcome: RunOutcome
    result: str = ""
    error: str = ""


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def reply_text(raw: Any) -> str:
    """Text of a ``system.ask`` result, which may be a str or a result dict.

    Raises ``RuntimeError`` (with the dict's content) when the result reports
    an error, e.g. ``{"content": "Unknown agent: x", "error": True}``, so
    callers record the run as failed rather than as a successful reply.
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        if raw.get("error"):
            raise RuntimeError(str(raw.get("content") or "agent run failed"))
        return str(raw.get("content", ""))
    return "" if raw is None else str(raw)


def _requested_tools(task: ScheduledTask) -> List[str]:
    raw = task.tools if isinstance(task.tools, list) else (task.tools or "").split(",")
    return [t.strip() for t in raw if t and t.strip()]


class TaskScheduler:
    """Scheduler that polls for due tasks and executes them.

    Parameters
    ----------
    store:
        The persistence backend.
    system:
        Optional ``JarvisSystem`` instance for executing prompts.
    poll_interval:
        Seconds between poll cycles (default 60).
    bus:
        Optional event bus for ``SCHEDULER_TASK_START`` / ``SCHEDULER_TASK_END``.
        END is published for every outcome (success, failed, skipped, missed);
        skipped and missed runs never start, so they emit END without START.
    policy:
        Which agents may run unattended. ``None`` is unrestricted, which keeps
        in-process callers (operators, proactive agents) working; the
        ``jarvis scheduler start`` daemon passes a deny-by-default policy.
    """

    def __init__(
        self,
        store: SchedulerStore,
        system: Any = None,
        *,
        poll_interval: int = 60,
        bus: Any = None,
        policy: Optional[RunPolicy] = None,
    ) -> None:
        self._store = store
        self._system = system
        self._poll_interval = poll_interval
        self._bus = bus
        self._policy = policy or RunPolicy()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -- Public API ----------------------------------------------------------

    def start(self) -> None:
        """Start the background polling daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="jarvis-scheduler"
        )
        self._thread.start()
        logger.info("Scheduler started (poll_interval=%ds)", self._poll_interval)

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval + 5)
            self._thread = None
        logger.info("Scheduler stopped")

    def create_task(
        self,
        prompt: str,
        schedule_type: str,
        schedule_value: str,
        **kwargs: Any,
    ) -> ScheduledTask:
        """Create and persist a new scheduled task."""
        task = ScheduledTask(
            id=uuid.uuid4().hex[:16],
            prompt=prompt,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            agent=kwargs.get("agent", "simple"),
            tools=kwargs.get("tools", ""),
            context_mode=kwargs.get("context_mode", "isolated"),
            metadata=kwargs.get("metadata", {}),
        )
        task.next_run = self._compute_next_run(task)
        with self._lock:
            self._store.save_task(task.to_dict())
        return task

    def list_tasks(self, *, status: Optional[str] = None) -> List[ScheduledTask]:
        """Return tasks, optionally filtered by *status*."""
        with self._lock:
            rows = self._store.list_tasks(status=status)
        return [ScheduledTask.from_dict(r) for r in rows]

    def pause_task(self, task_id: str) -> None:
        """Pause an active task."""
        with self._lock:
            d = self._store.get_task(task_id)
            if d is None:
                raise KeyError(f"Task not found: {task_id}")
            d["status"] = "paused"
            self._store.update_task(d)

    def resume_task(self, task_id: str) -> None:
        """Resume a paused task."""
        with self._lock:
            d = self._store.get_task(task_id)
            if d is None:
                raise KeyError(f"Task not found: {task_id}")
            d["status"] = "active"
            # Recompute next_run from now
            task = ScheduledTask.from_dict(d)
            task.next_run = self._compute_next_run(task)
            self._store.update_task(task.to_dict())

    def cancel_task(self, task_id: str) -> None:
        """Cancel a task (sets status to cancelled)."""
        with self._lock:
            d = self._store.get_task(task_id)
            if d is None:
                raise KeyError(f"Task not found: {task_id}")
            d["status"] = "cancelled"
            d["next_run"] = None
            self._store.update_task(d)

    # -- Execution -----------------------------------------------------------

    def run_pending(self) -> int:
        """Run every task that is due now, once each; return how many were due.

        A crash in one task is logged and does not stop the others.
        """
        with self._lock:
            due = self._store.get_due_tasks(_now_iso())
        for task_dict in due:
            try:
                self._execute_task(ScheduledTask.from_dict(task_dict))
            except Exception:
                logger.exception("Scheduled task %s crashed", task_dict.get("id"))
        return len(due)

    def _poll_loop(self) -> None:
        """Poll for due tasks and execute them until stopped."""
        while not self._stop_event.is_set():
            try:
                self.run_pending()
            except Exception:
                logger.exception("Scheduler poll error")
            self._stop_event.wait(timeout=self._poll_interval)

    def run_now(self, task_id: str) -> RunRecord:
        """Run *task_id* once, immediately, and record it like a scheduled run.

        For manual testing (``jarvis scheduler run-task``): the schedule is not
        advanced, and the agent allowlist and misfire window do not apply.
        Raises ``KeyError`` for an unknown task.
        """
        with self._lock:
            d = self._store.get_task(task_id)
        if d is None:
            raise KeyError(f"Task not found: {task_id}")
        task = ScheduledTask.from_dict(d)
        started = datetime.now(timezone.utc)
        requested = _requested_tools(task)
        record = self._run(task, requested, started)
        self._finish(task, record, requested, started)
        return record

    def _execute_task(self, task: ScheduledTask) -> None:
        """Run one due task at most once for its slot and record the outcome."""
        started = datetime.now(timezone.utc)
        if not self._claim(task, started):
            return
        requested = _requested_tools(task)
        record = self._skip_reason(task, started)
        if record is None:
            record = self._run(task, requested, started)
        self._finish(task, record, requested, started)

    def _claim(self, task: ScheduledTask, started: datetime) -> bool:
        """Advance the task's schedule before running it.

        Doing this first means a run that crashes (or a second scheduler that
        sees the same row) cannot repeat the slot: only the caller whose
        compare-and-set succeeds runs it.

        Only a bad schedule pauses the task. Environment problems (e.g.
        croniter missing) propagate, so the task is retried on the next poll.
        A one-shot task for an agent outside the allowlist is paused rather
        than completed: it has no later slot, and pausing with ``last_run``
        unset lets ``resume`` run it once the agent is allowed.
        """
        if task.schedule_type == "once" and not self._policy.admits(task.agent):
            with self._lock:
                return self._store.claim_task(
                    task.id,
                    expected_next_run=task.next_run,
                    next_run=task.next_run,
                    last_run=task.last_run,
                    status="paused",
                )
        started_iso = started.isoformat()
        try:
            after = ScheduledTask.from_dict({**task.to_dict(), "last_run": started_iso})
            next_run = self._compute_next_run(after)
        # Bad cron (CroniterBadCronError), interval, or ISO time raise ValueError.
        # Not bare KeyError: that would pause a valid task over a code bug.
        except (ValueError, ZoneInfoNotFoundError) as exc:
            logger.error(
                "Task %s has an invalid schedule, pausing it: %s", task.id, exc
            )
            self._pause_invalid(task.id)
            return False
        with self._lock:
            claimed = self._store.claim_task(
                task.id,
                expected_next_run=task.next_run,
                next_run=next_run,
                last_run=started_iso,
                status="active" if next_run is not None else "completed",
            )
        if not claimed:
            logger.info("Task %s was claimed elsewhere or is no longer active", task.id)
        return claimed

    def _pause_invalid(self, task_id: str) -> None:
        with self._lock:
            d = self._store.get_task(task_id)
            if d is not None:
                d["status"] = "paused"
                self._store.update_task(d)

    def _skip_reason(self, task: ScheduledTask, now: datetime) -> Optional[RunRecord]:
        """The skipped or missed record if the task must not run now, else ``None``."""
        if not self._policy.admits(task.agent):
            return RunRecord(
                RunOutcome.SKIPPED,
                error=f"agent '{task.agent}' not in scheduler.allowed_agents",
            )
        misfire = missed_by(task.metadata or {}, self._latest_slot(task, now), now)
        if misfire is not None:
            return RunRecord(RunOutcome.MISSED, error=misfire.message)
        return None

    def _run(
        self, task: ScheduledTask, requested: List[str], started: datetime
    ) -> RunRecord:
        """Execute the prompt and return what it produced."""
        self._publish(
            EventType.SCHEDULER_TASK_START,
            {
                "task_id": task.id,
                "agent": task.agent,
                "prompt": task.prompt,
                "started_at": started.isoformat(),
            },
        )
        if self._system is None:
            return RunRecord(
                RunOutcome.SUCCESS, f"[dry-run] Would execute: {task.prompt}"
            )
        ask_kwargs: Dict[str, Any] = {
            "agent": task.agent,
            "tools": requested or None,
        }
        meta = task.metadata or {}
        if meta.get("operator_id"):
            ask_kwargs["system_prompt"] = meta.get("system_prompt", "")
            ask_kwargs["operator_id"] = meta["operator_id"]
        try:
            text = reply_text(self._system.ask(task.prompt, **ask_kwargs))
        except Exception as exc:
            logger.error("Task %s failed: %s", task.id, exc)
            return RunRecord(RunOutcome.FAILED, error=f"{type(exc).__name__}: {exc}")
        return RunRecord(RunOutcome.SUCCESS, text)

    def _finish(
        self,
        task: ScheduledTask,
        record: RunRecord,
        requested: List[str],
        started: datetime,
    ) -> None:
        """Record the run, write the audit line, and announce the end."""
        finished = datetime.now(timezone.utc)
        try:
            with self._lock:
                self._store.log_run(
                    task_id=task.id,
                    started_at=started.isoformat(),
                    finished_at=finished.isoformat(),
                    outcome=record.outcome,
                    result=record.result,
                    error=record.error,
                )
        except Exception:
            # The slot is already claimed, so losing the log cannot cause a re-run.
            logger.exception("Could not record run of task %s", task.id)
        logger.info(
            audit_line(
                task.id,
                task.agent,
                record.outcome,
                requested,
                self._policy,
                (finished - started).total_seconds(),
            )
        )
        self._publish(
            EventType.SCHEDULER_TASK_END,
            {
                "task_id": task.id,
                "agent": task.agent,
                "success": record.outcome is RunOutcome.SUCCESS,
                "outcome": record.outcome.value,
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "result": record.result,
                "error": record.error,
            },
        )

    def _publish(self, event_type: EventType, payload: Dict[str, Any]) -> None:
        if self._bus is not None:
            self._bus.publish(event_type, payload)

    def _compute_next_run(self, task: ScheduledTask) -> Optional[str]:
        """Compute the next run time for a task.

        Returns an ISO 8601 string, or ``None`` if the task should not run again.
        """
        now = datetime.now(timezone.utc)

        if task.schedule_type == "once":
            # If already run, no more runs
            if task.last_run is not None:
                return None
            # Otherwise the schedule_value is the target ISO datetime
            return task.schedule_value

        if task.schedule_type == "interval":
            seconds = float(task.schedule_value)
            next_time = now + timedelta(seconds=seconds)
            return next_time.isoformat()

        if task.schedule_type == "cron":
            return self._compute_next_cron(
                task.schedule_value, now, _task_timezone(task)
            )

        return None

    @staticmethod
    def _latest_slot(task: ScheduledTask, now: datetime) -> Optional[str]:
        """The most recent slot at or before *now*: what a late run is late for.

        ``next_run`` is the first slot that was missed, which is days stale
        after the machine sleeps through several; measuring from it would skip
        a run that is only minutes past today's slot.
        """
        stored = task.next_run
        if not stored or task.schedule_type not in ("cron", "interval"):
            return stored
        try:
            first_missed = _as_utc(datetime.fromisoformat(stored))
            if task.schedule_type == "cron":
                previous = _cron_slot(
                    task.schedule_value, now, _task_timezone(task), previous=True
                )
                latest = max(first_missed, previous)
            else:
                latest = _latest_interval_slot(
                    first_missed, float(task.schedule_value), _as_utc(now)
                )
        except (ValueError, ZoneInfoNotFoundError):
            return stored
        return latest.isoformat()

    @staticmethod
    def _compute_next_cron(
        cron_expr: str,
        now: datetime,
        timezone_name: str | None = None,
    ) -> Optional[str]:
        """Compute the next run time from a cron expression, as UTC ISO 8601."""
        return _cron_slot(cron_expr, now, timezone_name).isoformat()


def _as_utc(moment: datetime) -> datetime:
    """Aware UTC datetime; naive values are taken as UTC."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _task_timezone(task: ScheduledTask) -> Optional[str]:
    return str((task.metadata or {}).get("timezone") or "") or None


def _cron_slot(
    cron_expr: str,
    now: datetime,
    timezone_name: Optional[str],
    *,
    previous: bool = False,
) -> datetime:
    """The cron slot after (or, with *previous*, before) *now*, in UTC.

    Evaluated in the task's IANA timezone so "07:00" means local 07:00.
    Missing cron support is fatal instead of silently changing semantics.
    """
    try:
        from croniter import croniter  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "croniter is required for cron schedules; reinstall OpenJarvis"
        ) from exc

    now = _as_utc(now)
    local_now = now.astimezone(ZoneInfo(timezone_name)) if timezone_name else now
    slots = croniter(cron_expr, local_now)
    slot = slots.get_prev(datetime) if previous else slots.get_next(datetime)
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=local_now.tzinfo)
    return slot.astimezone(timezone.utc)


def _latest_interval_slot(
    first_missed: datetime, seconds: float, now: datetime
) -> datetime:
    """The last slot of a fixed-interval schedule at or before *now*."""
    if seconds <= 0 or first_missed >= now:
        return first_missed
    step = timedelta(seconds=seconds)
    return first_missed + step * ((now - first_missed) // step)


__all__ = [
    "SCHEDULER_TASK_END",
    "SCHEDULER_TASK_START",
    "RunOutcome",
    "RunRecord",
    "ScheduledTask",
    "TaskScheduler",
    "reply_text",
]
