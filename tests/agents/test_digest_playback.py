"""DigestAutoplay — speak a fresh scheduled digest after its run (F-024 AC-004)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from openjarvis.agents.digest_playback import DigestAutoplay
from openjarvis.agents.digest_store import DigestArtifact, DigestStore
from openjarvis.core.config import DigestConfig, load_config
from openjarvis.core.events import EventBus, EventType


def _sync_spawn(target, *args):
    target(*args)


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "digest.db")


@pytest.fixture()
def audio(tmp_path):
    clip = tmp_path / "digest.mp3"
    clip.write_bytes(b"ID3fake")
    return clip


def _save(db_path, audio_path, generated_at=None):
    store = DigestStore(db_path)
    store.save(
        DigestArtifact(
            text="Good morning",
            audio_path=Path(audio_path),
            sections={},
            sources_used=[],
            generated_at=generated_at or datetime.now(),
            model_used="fake",
            voice_used="fake",
        )
    )
    store.close()


def _payload(**overrides):
    data = {
        "task_id": "t1",
        "agent": "morning_digest",
        "success": True,
        "outcome": "success",
        "started_at": (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "result": "",
        "error": "",
    }
    data.update(overrides)
    return data


def _listener(db_path, played, *, autoplay=True, open_store=None):
    return DigestAutoplay(
        autoplay_enabled=lambda: autoplay,
        open_store=open_store or (lambda: DigestStore(db_path)),
        play=played.append,
        spawn=_sync_spawn,
    )


def _publish(listener, **overrides):
    bus = EventBus()
    listener.attach(bus)
    bus.publish(EventType.SCHEDULER_TASK_END, _payload(**overrides))


class TestPlays:
    def test_plays_fresh_audio_after_successful_digest_run(self, db_path, audio):
        _save(db_path, audio)
        played = []

        _publish(_listener(db_path, played))

        assert played == [str(audio)]

    def test_autoplay_setting_is_read_per_event(self, db_path, audio):
        _save(db_path, audio)
        played = []
        state = {"on": False}
        listener = DigestAutoplay(
            autoplay_enabled=lambda: state["on"],
            open_store=lambda: DigestStore(db_path),
            play=played.append,
            spawn=_sync_spawn,
        )
        bus = EventBus()
        listener.attach(bus)

        bus.publish(EventType.SCHEDULER_TASK_END, _payload())
        state["on"] = True
        bus.publish(EventType.SCHEDULER_TASK_END, _payload())

        assert played == [str(audio)]

    def test_playback_is_spawned_not_run_inline(self, db_path, audio):
        _save(db_path, audio)
        spawned = []
        listener = DigestAutoplay(
            autoplay_enabled=lambda: True,
            open_store=lambda: DigestStore(db_path),
            play=lambda path: None,
            spawn=lambda target, *args: spawned.append(args),
        )

        _publish(listener)

        assert spawned == [(str(audio),)]


class TestDoesNotPlay:
    def test_autoplay_off(self, db_path, audio):
        _save(db_path, audio)
        played = []

        _publish(_listener(db_path, played, autoplay=False))

        assert played == []

    def test_failed_run(self, db_path, audio):
        _save(db_path, audio)
        played = []

        _publish(_listener(db_path, played), success=False, outcome="failed")

        assert played == []

    @pytest.mark.parametrize("outcome", ["skipped", "missed"])
    def test_skipped_or_missed_run(self, db_path, audio, outcome):
        _save(db_path, audio)
        played = []

        _publish(_listener(db_path, played), success=False, outcome=outcome)

        assert played == []

    def test_other_agent(self, db_path, audio):
        _save(db_path, audio)
        played = []

        _publish(_listener(db_path, played), agent="simple")

        assert played == []

    def test_stale_artifact_from_before_the_run(self, db_path, audio):
        _save(db_path, audio, generated_at=datetime.now() - timedelta(hours=1))
        played = []

        _publish(_listener(db_path, played))

        assert played == []

    def test_failed_tts_empty_audio_path(self, db_path):
        _save(db_path, Path(""))
        played = []

        _publish(_listener(db_path, played))

        assert played == []

    def test_audio_file_missing(self, db_path, tmp_path):
        _save(db_path, tmp_path / "gone.mp3")
        played = []

        _publish(_listener(db_path, played))

        assert played == []

    def test_no_artifact(self, db_path):
        played = []

        _publish(_listener(db_path, played))

        assert played == []

    def test_missing_started_at(self, db_path, audio):
        _save(db_path, audio)
        played = []

        _publish(_listener(db_path, played), started_at=None)

        assert played == []


class TestErrorsSwallowed:
    def test_store_error_does_not_raise(self, db_path):
        played = []

        def _broken_store():
            raise RuntimeError("db locked")

        listener = _listener(db_path, played, open_store=_broken_store)

        listener.on_task_end(type("E", (), {"data": _payload(), "event_type": "x"})())

        assert played == []

    def test_bad_started_at_does_not_raise(self, db_path, audio):
        _save(db_path, audio)
        played = []
        listener = _listener(db_path, played)

        listener.on_task_end(type("E", (), {"data": _payload(started_at="garbage")})())

        assert played == []

    def test_event_without_data_does_not_raise(self, db_path):
        played = []

        _listener(db_path, played).on_task_end(object())

        assert played == []


class TestAutoplayConfig:
    def test_autoplay_defaults_to_false(self):
        assert DigestConfig().autoplay is False

    def test_autoplay_loads_from_toml(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("[digest]\nautoplay = true\n")

        assert load_config(path).digest.autoplay is True

    def test_default_listener_reads_config(self, tmp_path, monkeypatch, audio):
        home = tmp_path / "home"
        home.mkdir()
        (home / "config.toml").write_text("[digest]\nautoplay = true\n")
        monkeypatch.setenv("OPENJARVIS_HOME", str(home))
        load_config.cache_clear()
        _save(str(home / "digest.db"), audio)
        played = []

        listener = DigestAutoplay(play=played.append, spawn=_sync_spawn)
        _publish(listener)

        assert played == [str(audio)]
