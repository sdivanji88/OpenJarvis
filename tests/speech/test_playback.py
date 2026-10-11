"""play_audio — argv-only playback with fallbacks that never raises (F-024)."""

from __future__ import annotations

import subprocess

import pytest

from openjarvis.speech import playback
from openjarvis.speech.playback import play_audio


class _FakeRun:
    """Stands in for ``subprocess.run``; *outcomes* maps player -> exception."""

    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        exc = self.outcomes.get(argv[0])
        if exc is not None:
            raise exc
        return subprocess.CompletedProcess(argv, 0)


@pytest.fixture()
def fake_run(monkeypatch):
    def _install(outcomes=None):
        run = _FakeRun(outcomes)
        monkeypatch.setattr(playback.subprocess, "run", run)
        return run

    return _install


def _all_fail(exc):
    return {name: exc for name in ("afplay", "ffplay", "paplay", "aplay")}


class TestPlayAudio:
    def test_first_player_success_returns_true(self, fake_run, tmp_path):
        run = fake_run()
        clip = tmp_path / "digest.mp3"

        assert play_audio(clip) is True
        assert [argv for argv, _ in run.calls] == [["afplay", str(clip)]]

    def test_uses_argv_list_never_shell(self, fake_run):
        run = fake_run()

        play_audio("/tmp/a b; rm -rf ~.mp3")

        argv, kwargs = run.calls[0]
        assert isinstance(argv, list)
        assert argv[-1] == "/tmp/a b; rm -rf ~.mp3"
        assert kwargs.get("shell", False) is False
        assert kwargs["timeout"] > 0

    def test_falls_back_in_order_when_player_missing(self, fake_run):
        run = fake_run(
            {
                "afplay": FileNotFoundError("afplay"),
                "ffplay": subprocess.CalledProcessError(1, "ffplay"),
            }
        )

        assert play_audio("clip.wav") is True
        assert [argv[0] for argv, _ in run.calls] == ["afplay", "ffplay", "paplay"]
        assert run.calls[1][0] == ["ffplay", "-nodisp", "-autoexit", "clip.wav"]

    @pytest.mark.parametrize(
        "exc",
        [FileNotFoundError("missing"), subprocess.CalledProcessError(1, "x")],
        ids=["not-installed", "player-failed"],
    )
    def test_returns_false_when_nothing_works(self, fake_run, exc):
        run = fake_run(_all_fail(exc))

        assert play_audio("clip.wav") is False
        assert [argv[0] for argv, _ in run.calls] == [
            "afplay",
            "ffplay",
            "paplay",
            "aplay",
        ]

    def test_timeout_returns_false_without_replaying(self, fake_run):
        run = fake_run({"afplay": subprocess.TimeoutExpired("afplay", 900)})

        assert play_audio("clip.wav") is False
        assert len(run.calls) == 1

    def test_permission_error_falls_through(self, fake_run):
        run = fake_run({"afplay": PermissionError("denied")})

        assert play_audio("clip.wav") is True
        assert len(run.calls) == 2

    def test_nul_byte_path_returns_false_without_raising(self):
        # Real subprocess.run: it raises ValueError before spawning anything.
        assert play_audio("/tmp/x\x00.mp3") is False

    def test_digest_cmd_uses_shared_helper(self):
        from openjarvis.cli import digest_cmd

        assert digest_cmd._play_audio is play_audio
