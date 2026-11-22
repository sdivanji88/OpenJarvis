"""Scheduler daemon end to end: due digest task -> run -> log -> spoken (F-024).

Real SchedulerStore, TaskScheduler, RunPolicy, OnDemandSystem, EventBus,
DigestAutoplay, DigestStore and config loading, all under a tmp
OPENJARVIS_HOME. Only the JarvisSystem build and the audio player are fakes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from openjarvis.agents.digest_playback import DigestAutoplay
from openjarvis.agents.digest_store import DigestArtifact, DigestStore
from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.scheduler.policy import RunPolicy
from openjarvis.scheduler.runtime import OnDemandSystem
from openjarvis.scheduler.scheduler import ScheduledTask, TaskScheduler
from openjarvis.scheduler.store import SchedulerStore
from openjarvis.security.tool_allowlist import restrict_process_tools, tool_permitted

_TOOLS = ["digest_collect", "text_to_speech"]


class _DigestSystem:
    """Stands in for a built JarvisSystem running the morning_digest agent."""

    def __init__(self, audio_path, asks):
        self.audio_path = audio_path
        self.asks = asks

    def ask(self, prompt, **kwargs):
        permitted = {t for t in [*_TOOLS, "shell_exec"] if tool_permitted(t)}
        self.asks.append({"kwargs": kwargs, "permitted": permitted})
        store = DigestStore()
        store.save(
            DigestArtifact(
                text="hi",
                audio_path=self.audio_path,
                sections={},
                sources_used=[],
                generated_at=datetime.now(),
                model_used="fake",
                voice_used="fake",
            )
        )
        store.close()
        return {"content": "hi", "usage": {}}

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _unrestricted_after_test():
    yield
    restrict_process_tools(None)


@pytest.fixture()
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("OPENJARVIS_HOME", str(path))
    load_config.cache_clear()
    return path


def _write_config(home, *, autoplay):
    (home / "config.toml").write_text(
        "[scheduler]\n"
        'allowed_agents = ["morning_digest"]\n'
        'allowed_tools = ["digest_collect", "text_to_speech"]\n'
        "[digest]\n"
        f"autoplay = {'true' if autoplay else 'false'}\n"
    )
    load_config.cache_clear()


def _due_digest_task(store):
    task = ScheduledTask(
        id="digest0700",
        prompt="Generate my morning digest",
        schedule_type="cron",
        schedule_value="0 7 * * *",
        next_run=(datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(),
        agent="morning_digest",
        metadata={"timezone": "Asia/Kolkata", "misfire_grace_minutes": 180},
    )
    store.save_task(task.to_dict())


def _run_daemon_cycle(home, tmp_path):
    """One poll of the daemon as ``jarvis scheduler start`` wires it."""
    audio = tmp_path / "digest.mp3"
    audio.write_bytes(b"ID3fake")
    asks, played = [], []
    store = SchedulerStore(home / "scheduler.db")
    _due_digest_task(store)

    policy = RunPolicy.from_config(load_config().scheduler)
    restrict_process_tools(policy.allowed_tools)
    system = OnDemandSystem(
        credentials_path=home / "credentials.toml",
        build=lambda: _DigestSystem(audio, asks),
    )
    bus = EventBus()
    DigestAutoplay(play=played.append, spawn=lambda fn, *a: fn(*a)).attach(bus)
    due = TaskScheduler(store, system, bus=bus, policy=policy).run_pending()
    return store, due, asks, played, audio


def test_due_digest_runs_logs_text_advances_and_plays(home, tmp_path):
    _write_config(home, autoplay=True)

    store, due, asks, played, audio = _run_daemon_cycle(home, tmp_path)
    try:
        log = store.get_run_logs("digest0700")
        task = store.get_task("digest0700")
    finally:
        store.close()

    assert due == 1
    assert [entry["result"] for entry in log] == ["hi"]
    assert log[0]["success"] == 1
    assert datetime.fromisoformat(task["next_run"]) > datetime.now(timezone.utc)
    assert task["status"] == "active"
    assert asks[0]["kwargs"]["agent"] == "morning_digest"
    assert asks[0]["permitted"] == set(_TOOLS)
    assert played == [str(audio)]


def test_autoplay_off_runs_but_stays_silent(home, tmp_path):
    _write_config(home, autoplay=False)

    store, due, _asks, played, _audio = _run_daemon_cycle(home, tmp_path)
    try:
        log = store.get_run_logs("digest0700")
    finally:
        store.close()

    assert due == 1
    assert log[0]["result"] == "hi"
    assert played == []


def test_unconfigured_daemon_skips_digest(home, tmp_path):
    store, due, asks, played, _audio = _run_daemon_cycle(home, tmp_path)
    try:
        log = store.get_run_logs("digest0700")
    finally:
        store.close()

    assert due == 1
    assert asks == []
    assert log[0]["outcome"] == "skipped"
    assert played == []
