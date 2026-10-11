"""Unattended execution in TaskScheduler.run_pending (F-024 AC-001..AC-003)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.scheduler import scheduler as scheduler_mod
from openjarvis.scheduler.policy import RunPolicy
from openjarvis.scheduler.scheduler import ScheduledTask, TaskScheduler
from openjarvis.scheduler.store import SchedulerStore


@pytest.fixture()
def store(tmp_path):
    s = SchedulerStore(tmp_path / "scheduler.db")
    yield s
    s.close()


@pytest.fixture()
def bus():
    return EventBus(record_history=True)


class _FakeSystem:
    """Records ``ask`` calls; replies with *reply* or raises *exc*."""

    def __init__(self, reply=None, exc=None, on_ask=None):
        self.reply = reply
        self.exc = exc
        self.on_ask = on_ask
        self.calls = []

    def ask(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        if self.on_ask is not None:
            self.on_ask()
        if self.exc is not None:
            raise self.exc
        return self.reply


def _ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _save_due(store, task_id="t1", *, agent="simple", next_run=None, **kw):
    task = ScheduledTask(
        id=task_id,
        prompt=kw.pop("prompt", "say hello"),
        schedule_type=kw.pop("schedule_type", "interval"),
        schedule_value=kw.pop("schedule_value", "3600"),
        next_run=next_run or _ago(minutes=1),
        agent=agent,
        **kw,
    )
    store.save_task(task.to_dict())
    return task


def _events(bus, event_type):
    return [e for e in bus.history if e.event_type is event_type]


def _next_run(store, task_id="t1"):
    return datetime.fromisoformat(store.get_task(task_id)["next_run"])


# -- AC-001: real execution, text log, claim before run ----------------------


class TestExecution:
    def test_dict_reply_is_logged_as_content_text(self, store):
        _save_due(store)
        system = _FakeSystem(reply={"content": "hello there", "usage": {"t": 3}})

        assert TaskScheduler(store, system).run_pending() == 1

        log = store.get_run_logs("t1")[0]
        assert log["success"] == 1
        assert log["outcome"] == "success"
        assert log["result"] == "hello there"

    @pytest.mark.parametrize(("reply", "text"), [("plain", "plain"), (None, "")])
    def test_non_dict_reply_is_logged_as_text(self, store, reply, text):
        _save_due(store)

        TaskScheduler(store, _FakeSystem(reply=reply)).run_pending()

        log = store.get_run_logs("t1")[0]
        assert log["success"] == 1
        assert log["result"] == text

    def test_error_result_dict_is_recorded_as_failed(self, store, bus):
        _save_due(store)
        system = _FakeSystem(reply={"content": "Unknown agent: x", "error": True})

        TaskScheduler(store, system, bus=bus).run_pending()

        log = store.get_run_logs("t1")[0]
        assert log["success"] == 0
        assert log["outcome"] == "failed"
        assert log["result"] == ""
        assert "Unknown agent: x" in log["error"]
        (end,) = _events(bus, EventType.SCHEDULER_TASK_END)
        assert end.data["outcome"] == "failed"
        assert end.data["success"] is False

    def test_next_run_is_advanced_before_ask_runs(self, store):
        original = _save_due(store).next_run
        seen = {}

        def _inspect():
            seen.update(store.get_task("t1"))

        TaskScheduler(store, _FakeSystem(reply="ok", on_ask=_inspect)).run_pending()

        assert seen["next_run"] != original
        assert datetime.fromisoformat(seen["next_run"]) > datetime.now(timezone.utc)
        assert seen["last_run"] is not None

    def test_failing_ask_logs_failure_and_does_not_rerun_slot(self, store):
        _save_due(store)
        system = _FakeSystem(exc=RuntimeError("engine down"))
        sched = TaskScheduler(store, system)

        sched.run_pending()
        second = sched.run_pending()

        log = store.get_run_logs("t1")[0]
        assert log["success"] == 0
        assert log["error"] == "RuntimeError: engine down"
        assert _next_run(store) > datetime.now(timezone.utc)
        assert second == 0
        assert len(system.calls) == 1

    def test_log_run_failure_is_swallowed_and_not_rerun(self, store, monkeypatch):
        _save_due(store)

        def _broken_log(**_):
            raise OSError("disk full")

        monkeypatch.setattr(store, "log_run", _broken_log)
        system = _FakeSystem(reply="ok")
        sched = TaskScheduler(store, system)

        assert sched.run_pending() == 1
        assert sched.run_pending() == 0
        assert len(system.calls) == 1

    def test_lost_claim_does_not_run(self, store, bus, monkeypatch):
        _save_due(store)
        stale_snapshot = store.get_due_tasks(datetime.now(timezone.utc).isoformat())
        first = _FakeSystem(reply="first")
        TaskScheduler(store, first).run_pending()

        monkeypatch.setattr(store, "get_due_tasks", lambda _now: stale_snapshot)
        second = _FakeSystem(reply="second")
        TaskScheduler(store, second, bus=bus).run_pending()

        assert len(first.calls) == 1
        assert second.calls == []
        assert len(store.get_run_logs("t1")) == 1
        assert bus.history == []

    def test_invalid_cron_pauses_task_without_running(self, store):
        _save_due(store, schedule_type="cron", schedule_value="not a cron")
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system).run_pending()

        assert store.get_task("t1")["status"] == "paused"
        assert system.calls == []

    @pytest.mark.parametrize(
        ("schedule_type", "value", "metadata"),
        [
            ("interval", "soon", {}),
            ("cron", "0 7 * * *", {"timezone": "Nowhere/Atlantis"}),
        ],
        ids=["bad-interval", "unknown-timezone"],
    )
    def test_other_schedule_errors_pause(self, store, schedule_type, value, metadata):
        _save_due(
            store, schedule_type=schedule_type, schedule_value=value, metadata=metadata
        )

        TaskScheduler(store, _FakeSystem(reply="ok")).run_pending()

        assert store.get_task("t1")["status"] == "paused"

    @pytest.mark.parametrize(
        "exc",
        [RuntimeError("croniter is required for cron schedules"), KeyError("bug")],
        ids=["missing-croniter", "unrelated-keyerror"],
    )
    def test_non_schedule_errors_do_not_pause(self, store, monkeypatch, exc):
        original = _save_due(store, schedule_type="cron", schedule_value="0 7 * * *")

        def _raise(*_args, **_kwargs):
            raise exc

        monkeypatch.setattr(TaskScheduler, "_compute_next_cron", _raise)
        system = _FakeSystem(reply="ok")

        assert TaskScheduler(store, system).run_pending() == 1

        task = store.get_task("t1")
        assert task["status"] == "active"
        assert task["next_run"] == original.next_run
        assert system.calls == []

    def test_requested_tools_are_passed_to_ask(self, store):
        _save_due(store, tools="digest_collect, text_to_speech")
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system).run_pending()

        _prompt, kwargs = system.calls[0]
        assert kwargs["agent"] == "simple"
        assert kwargs["tools"] == ["digest_collect", "text_to_speech"]


# -- AC-002: agent allowlist -------------------------------------------------


class TestAgentAllowlist:
    def test_disallowed_agent_is_skipped_and_logged(self, store, bus):
        _save_due(store, agent="simple")
        system = _FakeSystem(reply="ok")
        policy = RunPolicy(allowed_agents=frozenset({"morning_digest"}))

        TaskScheduler(store, system, bus=bus, policy=policy).run_pending()

        log = store.get_run_logs("t1")[0]
        assert system.calls == []
        assert log["success"] == 0
        assert log["outcome"] == "skipped"
        assert log["error"] == "agent 'simple' not in scheduler.allowed_agents"
        assert _events(bus, EventType.SCHEDULER_TASK_START) == []
        (end,) = _events(bus, EventType.SCHEDULER_TASK_END)
        assert end.data["outcome"] == "skipped"
        assert end.data["success"] is False

    def test_skipped_once_task_is_paused_not_completed(self, store):
        due = _ago(minutes=1)
        _save_due(store, agent="simple", schedule_type="once", schedule_value=due)
        policy = RunPolicy(allowed_agents=frozenset())

        TaskScheduler(store, _FakeSystem(), policy=policy).run_pending()

        task = store.get_task("t1")
        assert task["status"] == "paused"
        assert task["last_run"] is None
        assert store.get_run_logs("t1")[0]["outcome"] == "skipped"

    def test_skipped_once_task_runs_after_allowlisting_and_resume(self, store):
        due = _ago(minutes=1)
        _save_due(store, agent="simple", schedule_type="once", schedule_value=due)
        denied = RunPolicy(allowed_agents=frozenset())
        TaskScheduler(store, _FakeSystem(), policy=denied).run_pending()

        system = _FakeSystem(reply="ran")
        allowed = TaskScheduler(
            store, system, policy=RunPolicy(allowed_agents=frozenset({"simple"}))
        )
        allowed.resume_task("t1")
        allowed.run_pending()

        assert len(system.calls) == 1
        assert store.get_task("t1")["status"] == "completed"
        assert store.get_run_logs("t1")[0]["outcome"] == "success"

    def test_skipped_task_still_advances_next_run(self, store):
        _save_due(store, agent="simple")
        policy = RunPolicy(allowed_agents=frozenset())

        TaskScheduler(store, _FakeSystem(), policy=policy).run_pending()

        assert _next_run(store) > datetime.now(timezone.utc)

    def test_allowlisted_agent_runs(self, store):
        _save_due(store, agent="morning_digest")
        system = _FakeSystem(reply="digest")
        policy = RunPolicy(allowed_agents=frozenset({"morning_digest"}))

        TaskScheduler(store, system, policy=policy).run_pending()

        assert len(system.calls) == 1
        assert store.get_run_logs("t1")[0]["result"] == "digest"

    def test_default_policy_is_unrestricted(self, store):
        _save_due(store, agent="anything")
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system).run_pending()

        assert len(system.calls) == 1


# -- AC-003: misfire grace window --------------------------------------------


class TestMisfireGrace:
    def test_late_beyond_grace_is_missed(self, store, bus):
        _save_due(
            store,
            next_run=_ago(hours=4),
            schedule_value="86400",
            metadata={"misfire_grace_minutes": 180},
        )
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system, bus=bus).run_pending()

        log = store.get_run_logs("t1")[0]
        assert system.calls == []
        assert log["success"] == 0
        assert log["outcome"] == "missed"
        assert log["error"].endswith("min late (grace 180)")
        assert _next_run(store) > datetime.now(timezone.utc)
        (end,) = _events(bus, EventType.SCHEDULER_TASK_END)
        assert end.data["outcome"] == "missed"

    def test_within_grace_runs(self, store):
        _save_due(
            store,
            next_run=_ago(minutes=10),
            metadata={"misfire_grace_minutes": 180},
        )
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system).run_pending()

        assert len(system.calls) == 1

    @staticmethod
    def _daily_cron_at(when: datetime) -> str:
        return f"{when.minute} {when.hour} * * *"

    def test_cron_slept_through_days_runs_if_todays_slot_is_recent(self, store):
        # next_run is the first missed slot, days old; today's slot was 30 min ago.
        slot = datetime.now(timezone.utc) - timedelta(minutes=30)
        _save_due(
            store,
            next_run=_ago(days=3, minutes=30),
            schedule_type="cron",
            schedule_value=self._daily_cron_at(slot),
            metadata={"misfire_grace_minutes": 180, "timezone": "UTC"},
        )
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system).run_pending()

        assert len(system.calls) == 1

    def test_cron_slept_through_days_misses_if_todays_slot_is_stale(self, store):
        slot = datetime.now(timezone.utc) - timedelta(hours=4)
        _save_due(
            store,
            next_run=_ago(days=3, hours=4),
            schedule_type="cron",
            schedule_value=self._daily_cron_at(slot),
            metadata={"misfire_grace_minutes": 180, "timezone": "UTC"},
        )
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system).run_pending()

        assert system.calls == []
        assert store.get_run_logs("t1")[0]["outcome"] == "missed"

    def test_interval_lateness_counts_from_latest_slot(self, store):
        _save_due(
            store,
            next_run=_ago(hours=4, minutes=10),
            schedule_value="3600",
            metadata={"misfire_grace_minutes": 30},
        )
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system).run_pending()

        assert len(system.calls) == 1

    @pytest.mark.parametrize(
        "metadata",
        [{}, {"misfire_grace_minutes": "abc"}, {"misfire_grace_minutes": None}],
        ids=["no-setting", "garbage", "null"],
    )
    def test_without_valid_setting_old_task_catches_up(self, store, metadata):
        _save_due(store, next_run=_ago(days=2), metadata=metadata)
        system = _FakeSystem(reply="ok")

        TaskScheduler(store, system).run_pending()

        assert len(system.calls) == 1
        assert store.get_run_logs("t1")[0]["success"] == 1


# -- Events and audit log ----------------------------------------------------


class TestEventsAndAudit:
    def test_event_constants_are_eventtype_members(self):
        assert scheduler_mod.SCHEDULER_TASK_START is EventType.SCHEDULER_TASK_START
        assert scheduler_mod.SCHEDULER_TASK_END is EventType.SCHEDULER_TASK_END

    def test_start_and_end_payloads(self, store, bus):
        _save_due(store, agent="morning_digest", prompt="brief me")

        TaskScheduler(store, _FakeSystem(reply="done"), bus=bus).run_pending()

        (start,) = _events(bus, EventType.SCHEDULER_TASK_START)
        (end,) = _events(bus, EventType.SCHEDULER_TASK_END)
        assert start.data == {
            "task_id": "t1",
            "agent": "morning_digest",
            "prompt": "brief me",
            "started_at": start.data["started_at"],
        }
        assert set(end.data) == {
            "task_id",
            "agent",
            "success",
            "outcome",
            "started_at",
            "finished_at",
            "result",
            "error",
        }
        assert end.data["agent"] == "morning_digest"
        assert end.data["started_at"] == start.data["started_at"]
        assert end.data["outcome"] == "success"
        assert end.data["success"] is True
        assert end.data["result"] == "done"

    def test_failed_run_end_event(self, store, bus):
        _save_due(store)

        TaskScheduler(store, _FakeSystem(exc=ValueError("x")), bus=bus).run_pending()

        (end,) = _events(bus, EventType.SCHEDULER_TASK_END)
        assert end.data["outcome"] == "failed"
        assert end.data["success"] is False

    @staticmethod
    def _run_to_outcome(store, bus, outcome):
        """Drive one run_pending to *outcome* using the real scheduler paths."""
        policy = None
        system = _FakeSystem(reply="ok")
        if outcome == "failed":
            system = _FakeSystem(exc=RuntimeError("boom"))
        elif outcome == "skipped":
            policy = RunPolicy(allowed_agents=frozenset())
        if outcome == "missed":
            _save_due(
                store,
                next_run=_ago(hours=4),
                schedule_value="86400",
                metadata={"misfire_grace_minutes": 1},
            )
        else:
            _save_due(store)
        TaskScheduler(store, system, bus=bus, policy=policy).run_pending()

    @pytest.mark.parametrize("outcome", ["success", "failed", "skipped", "missed"])
    def test_end_payload_outcome_is_plain_str(self, store, bus, outcome):
        self._run_to_outcome(store, bus, outcome)

        (end,) = _events(bus, EventType.SCHEDULER_TASK_END)
        assert type(end.data["outcome"]) is str
        assert end.data["outcome"] == outcome
        assert end.data["success"] is (outcome == "success")

    @pytest.mark.parametrize("outcome", ["skipped", "missed"])
    def test_audit_line_renders_outcome_value(self, store, bus, caplog, outcome):
        with caplog.at_level(logging.INFO, logger="openjarvis.scheduler.scheduler"):
            self._run_to_outcome(store, bus, outcome)

        (audit,) = [m for m in caplog.messages if m.startswith("scheduled run ")]
        assert f"outcome={outcome} " in audit
        assert "RunOutcome." not in audit

    def test_audit_line_has_ids_but_no_prompt_or_result(self, store, caplog):
        _save_due(store, agent="morning_digest", prompt="SECRET-PROMPT")
        policy = RunPolicy(
            allowed_agents=frozenset({"morning_digest"}),
            allowed_tools=frozenset({"digest_collect"}),
        )
        system = _FakeSystem(reply={"content": "SECRET-RESULT"})

        with caplog.at_level(logging.INFO, logger="openjarvis.scheduler.scheduler"):
            TaskScheduler(store, system, policy=policy).run_pending()

        audit = [m for m in caplog.messages if m.startswith("scheduled run ")]
        assert len(audit) == 1
        assert "task=t1" in audit[0]
        assert "agent=morning_digest" in audit[0]
        assert "outcome=success" in audit[0]
        assert "permitted_tools=['digest_collect']" in audit[0]
        assert all("SECRET-PROMPT" not in m for m in caplog.messages)
        assert all("SECRET-RESULT" not in m for m in caplog.messages)
