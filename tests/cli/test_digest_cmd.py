"""Tests for `jarvis digest` CLI command."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from openjarvis.agents.digest_store import DigestArtifact, DigestStore


def test_digest_command_exists():
    """The digest command is registered on the CLI."""
    from openjarvis.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--help"])
    assert result.exit_code == 0
    assert "digest" in result.output.lower()


def test_digest_displays_cached(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "digest.db")
    store = DigestStore(db_path=db_path)
    store.save(
        DigestArtifact(
            text="# Messages\nYou have 3 emails.\n# Calendar\n2 meetings today.",
            audio_path=Path("/nonexistent/audio.mp3"),
            sections={},
            sources_used=["gmail"],
            generated_at=datetime.now(tz=timezone.utc),
            model_used="test",
            voice_used="jarvis",
        )
    )
    store.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--text-only", "--db-path", db_path])
    assert result.exit_code == 0
    assert "3 emails" in result.output


def _save_today(db_path: str, audio_path: Path) -> None:
    store = DigestStore(db_path=db_path)
    store.save(
        DigestArtifact(
            text="Good morning.",
            audio_path=audio_path,
            sections={},
            sources_used=["gmail"],
            generated_at=datetime.now(tz=timezone.utc),
            model_used="test",
            voice_used="v",
        )
    )
    store.close()


def test_digest_waits_for_playback_to_finish(tmp_path, monkeypatch):
    import time

    from openjarvis.cli import cli, digest_cmd

    audio = tmp_path / "digest.mp3"
    audio.write_bytes(b"mp3")
    db_path = str(tmp_path / "digest.db")
    _save_today(db_path, audio)
    played = []

    def slow_player(path: str) -> None:
        time.sleep(0.2)
        played.append(path)

    monkeypatch.setattr(digest_cmd, "_play_audio", slow_player)
    result = CliRunner().invoke(cli, ["digest", "--db-path", db_path])

    assert result.exit_code == 0
    assert played == [str(audio)]


def test_digest_without_audio_file_skips_playback(tmp_path, monkeypatch):
    from openjarvis.cli import cli, digest_cmd

    db_path = str(tmp_path / "digest.db")
    # A failed TTS run stores Path(""), which renders as "." and exists().
    _save_today(db_path, Path(""))
    played = []
    monkeypatch.setattr(digest_cmd, "_play_audio", played.append)

    result = CliRunner().invoke(cli, ["digest", "--db-path", db_path])

    assert result.exit_code == 0
    assert played == []


class _GeneratingJarvis:
    """Stands in for the SDK: ``ask`` saves a fresh digest with audio."""

    def __init__(self, db_path: str, audio: Path) -> None:
        self._db_path = db_path
        self._audio = audio

    def __call__(self) -> "_GeneratingJarvis":
        return self

    def __enter__(self) -> "_GeneratingJarvis":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def ask(self, prompt: str, **kwargs: object) -> None:
        _save_today(self._db_path, self._audio)


@pytest.mark.parametrize(("flags", "expected_plays"), [([], 1), (["--text-only"], 0)])
def test_fresh_digest_plays_unless_text_only(
    tmp_path, monkeypatch, flags, expected_plays
):
    import openjarvis.sdk
    from openjarvis.cli import cli, digest_cmd

    audio = tmp_path / "digest.mp3"
    audio.write_bytes(b"mp3")
    db_path = str(tmp_path / "digest.db")
    monkeypatch.setattr(openjarvis.sdk, "Jarvis", _GeneratingJarvis(db_path, audio))
    played = []
    monkeypatch.setattr(digest_cmd, "_play_audio", played.append)

    result = CliRunner().invoke(
        cli, ["digest", "--fresh", *flags, "--db-path", db_path]
    )

    assert result.exit_code == 0, result.output
    assert "Good morning." in result.output
    assert len(played) == expected_plays
    assert "TTS failed" not in result.output


def test_digest_no_cache(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "empty.db")
    runner = CliRunner()
    result = runner.invoke(cli, ["digest", "--db-path", db_path])
    assert result.exit_code == 0
    assert "No digest for today" in result.output
