"""Tests for ``jarvis operators logs``."""

from __future__ import annotations

from click.testing import CliRunner

from openjarvis.cli.operators_cmd import operators
from openjarvis.scheduler import store as store_mod
from openjarvis.scheduler.store import RunOutcome, SchedulerStore


def test_logs_show_each_run_outcome(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    seed = SchedulerStore(db_path)
    seed.log_run(
        "operator:researcher",
        "2026-10-11T01:30:00+00:00",
        "2026-10-11T01:31:00+00:00",
        RunOutcome.SUCCESS,
        result="digest ready",
    )
    seed.log_run(
        "operator:researcher",
        "2026-10-12T01:30:00+00:00",
        "2026-10-12T01:30:00+00:00",
        RunOutcome.MISSED,
    )
    seed.close()
    monkeypatch.setattr(
        store_mod, "open_default_store", lambda: SchedulerStore(db_path)
    )

    result = CliRunner().invoke(operators, ["logs", "researcher"])

    assert result.exit_code == 0
    assert "Error" not in result.output
    assert "success" in result.output
    assert "missed" in result.output
    assert "digest ready" in result.output


def test_logs_report_operator_without_runs(tmp_path, monkeypatch):
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setattr(
        store_mod, "open_default_store", lambda: SchedulerStore(db_path)
    )

    result = CliRunner().invoke(operators, ["logs", "nobody"])

    assert result.exit_code == 0
    assert "No logs found for operator nobody" in result.output
