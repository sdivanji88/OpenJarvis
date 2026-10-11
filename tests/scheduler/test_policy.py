"""RunPolicy allowlists, misfire grace, and the audit line (F-024 AC-002/AC-003)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from openjarvis.core.config import SchedulerConfig
from openjarvis.scheduler.policy import (
    MISFIRE_GRACE_KEY,
    RunPolicy,
    audit_line,
    missed_by,
)
from openjarvis.scheduler.store import RunOutcome

_NOW = datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc)


def _iso(minutes_ago: float) -> str:
    return (_NOW - timedelta(minutes=minutes_ago)).isoformat()


class TestFromConfig:
    def test_lists_become_frozensets(self):
        cfg = SchedulerConfig(
            allowed_agents=["morning_digest"],
            allowed_tools=["digest_collect", "text_to_speech"],
        )

        policy = RunPolicy.from_config(cfg)

        assert policy.allowed_agents == frozenset({"morning_digest"})
        assert policy.allowed_tools == frozenset({"digest_collect", "text_to_speech"})

    def test_comma_strings_are_split_and_stripped(self):
        cfg = SimpleNamespace(allowed_agents="a, b ,", allowed_tools=" x ")

        policy = RunPolicy.from_config(cfg)

        assert policy.allowed_agents == frozenset({"a", "b"})
        assert policy.allowed_tools == frozenset({"x"})

    def test_config_defaults_allow_nothing(self):
        policy = RunPolicy.from_config(SchedulerConfig())

        assert policy.allowed_agents == frozenset()
        assert policy.allowed_tools == frozenset()
        assert policy.admits("morning_digest") is False

    def test_missing_keys_allow_nothing(self):
        policy = RunPolicy.from_config(SimpleNamespace())

        assert policy.allowed_agents == frozenset()
        assert policy.allowed_tools == frozenset()


class TestAdmits:
    def test_default_policy_is_unrestricted(self):
        assert RunPolicy().admits("anything") is True

    def test_empty_allowlist_admits_nothing(self):
        assert RunPolicy(allowed_agents=frozenset()).admits("simple") is False

    def test_listed_agent_only(self):
        policy = RunPolicy(allowed_agents=frozenset({"morning_digest"}))

        assert policy.admits("morning_digest") is True
        assert policy.admits("orchestrator") is False


class TestPermittedTools:
    def test_unrestricted_without_tool_allowlist(self):
        assert RunPolicy().permitted_tools(["shell_exec"]) == "unrestricted"

    def test_requested_tools_filtered_by_allowlist(self):
        policy = RunPolicy(allowed_tools=frozenset({"digest_collect"}))

        assert policy.permitted_tools(["digest_collect", "shell_exec"]) == [
            "digest_collect"
        ]

    def test_no_request_reports_whole_allowlist(self):
        policy = RunPolicy(allowed_tools=frozenset({"b", "a"}))

        assert policy.permitted_tools([]) == ["a", "b"]

    def test_empty_allowlist_permits_nothing(self):
        policy = RunPolicy(allowed_tools=frozenset())

        assert policy.permitted_tools(["shell_exec"]) == []
        assert policy.permitted_tools([]) == []


class TestMissedBy:
    def test_beyond_grace_returns_minutes_late_and_grace(self):
        misfire = missed_by({"misfire_grace_minutes": 180}, _iso(240), _NOW)

        assert misfire.minutes_late == pytest.approx(240)
        assert misfire.grace_minutes == 180
        assert misfire.message == "240 min late (grace 180)"

    def test_key_constant_names_the_metadata_key(self):
        assert missed_by({MISFIRE_GRACE_KEY: 5}, _iso(6), _NOW) is not None

    def test_within_grace_is_none(self):
        assert missed_by({"misfire_grace_minutes": 180}, _iso(179), _NOW) is None

    def test_exactly_at_grace_is_none(self):
        assert missed_by({"misfire_grace_minutes": 180}, _iso(180), _NOW) is None

    def test_zero_grace_misses_any_lateness(self):
        misfire = missed_by({"misfire_grace_minutes": 0}, _iso(1), _NOW)

        assert misfire.minutes_late == pytest.approx(1)

    def test_numeric_string_grace_is_accepted(self):
        misfire = missed_by({"misfire_grace_minutes": "60"}, _iso(90), _NOW)

        assert misfire.minutes_late == pytest.approx(90)
        assert misfire.grace_minutes == 60

    @pytest.mark.parametrize(
        "metadata",
        [
            {},
            None,
            {"misfire_grace_minutes": None},
            {"misfire_grace_minutes": "abc"},
            {"misfire_grace_minutes": True},
            {"misfire_grace_minutes": -5},
            {"misfire_grace_minutes": [1]},
        ],
        ids=["absent", "no-metadata", "null", "garbage", "bool", "negative", "list"],
    )
    def test_missing_or_invalid_setting_never_misses(self, metadata):
        assert missed_by(metadata, _iso(10_000), _NOW) is None

    @pytest.mark.parametrize("scheduled", [None, "", "not-a-time"])
    def test_missing_or_unparsable_time_never_misses(self, scheduled):
        assert missed_by({"misfire_grace_minutes": 1}, scheduled, _NOW) is None

    def test_naive_times_are_utc(self):
        scheduled = (_NOW - timedelta(minutes=30)).replace(tzinfo=None).isoformat()
        now = _NOW.replace(tzinfo=None)

        misfire = missed_by({"misfire_grace_minutes": 10}, scheduled, now)

        assert misfire.minutes_late == pytest.approx(30)


class TestAuditLine:
    def test_contains_run_facts(self):
        policy = RunPolicy(
            allowed_agents=frozenset({"morning_digest"}),
            allowed_tools=frozenset({"digest_collect"}),
        )

        line = audit_line(
            "abc", "morning_digest", "success", ["text_to_speech"], policy, 1.26
        )

        assert line == (
            "scheduled run task=abc agent=morning_digest outcome=success "
            "requested_tools=['text_to_speech'] permitted_tools=[] duration_s=1.3"
        )

    def test_unrestricted_policy_is_reported(self):
        line = audit_line("t", "simple", "failed", [], RunPolicy(), 0)

        assert "permitted_tools=unrestricted" in line

    def test_run_outcome_member_renders_as_its_value(self):
        line = audit_line("t", "simple", RunOutcome.MISSED, [], RunPolicy(), 0)

        assert "outcome=missed " in line
        assert "RunOutcome" not in line
