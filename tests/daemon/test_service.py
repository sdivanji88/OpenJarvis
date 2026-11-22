"""generate_launchd_plist — plistlib-built LaunchAgent, never secrets (F-024)."""

from __future__ import annotations

import plistlib
import sys

import pytest

from openjarvis.daemon.service import generate_launchd_plist


def _parse(content: str) -> dict:
    return plistlib.loads(content.encode("utf-8"))


class TestSchedulerPlist:
    def test_custom_service_fields(self, tmp_path):
        out = tmp_path / "LaunchAgents" / "com.openjarvis.scheduler.plist"
        content = generate_launchd_plist(
            out,
            label="com.openjarvis.scheduler",
            program_args=["/opt/venv/bin/jarvis", "scheduler", "start"],
            stdout_path=tmp_path / "logs" / "scheduler.out.log",
            stderr_path=tmp_path / "logs" / "scheduler.err.log",
            min_restart_interval_s=30,
        )

        plist = _parse(content)
        assert plist == {
            "Label": "com.openjarvis.scheduler",
            "ProgramArguments": ["/opt/venv/bin/jarvis", "scheduler", "start"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "StandardOutPath": str(tmp_path / "logs" / "scheduler.out.log"),
            "StandardErrorPath": str(tmp_path / "logs" / "scheduler.err.log"),
            "ThrottleInterval": 30,
        }

    def test_writes_same_content_to_output(self, tmp_path):
        out = tmp_path / "nested" / "dir" / "x.plist"

        content = generate_launchd_plist(out, label="x")

        assert out.read_text() == content

    def test_never_emits_environment_variables(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CARTESIA_API_KEY", "ck-super-secret")

        content = generate_launchd_plist(
            label="com.openjarvis.scheduler",
            program_args=["/abs/jarvis", "scheduler", "start"],
        )

        assert "EnvironmentVariables" not in _parse(content)
        assert "ck-super-secret" not in content

    def test_xml_special_characters_are_escaped(self, tmp_path):
        weird = str(tmp_path / "a&b<c>" / "jarvis")

        content = generate_launchd_plist(label="x", program_args=[weird])

        assert _parse(content)["ProgramArguments"] == [weird]

    def test_restart_on_crash_only_respawns_after_failure(self):
        content = generate_launchd_plist(label="x", restart="on_crash")

        assert _parse(content)["KeepAlive"] == {"SuccessfulExit": False}

    def test_restart_always_keeps_alive_unconditionally(self):
        content = generate_launchd_plist(label="x", restart="always")

        assert _parse(content)["KeepAlive"] is True

    @pytest.mark.parametrize("restart", ["never", "", "ON_CRASH", None])
    def test_unknown_restart_raises_and_writes_nothing(self, tmp_path, restart):
        out = tmp_path / "x.plist"

        with pytest.raises(ValueError, match="restart must be"):
            generate_launchd_plist(out, label="x", restart=restart)

        assert not out.exists()

    def test_throttle_interval_omitted_without_min_restart_interval(self):
        content = generate_launchd_plist(
            label="x", restart="on_crash", min_restart_interval_s=None
        )

        assert "ThrottleInterval" not in _parse(content)


class TestGatewayDefault:
    def test_default_still_describes_gateway(self):
        plist = _parse(generate_launchd_plist())

        assert plist["Label"] == "com.openjarvis.gateway"
        assert plist["ProgramArguments"] == [
            sys.executable,
            "-m",
            "openjarvis.daemon.gateway",
        ]
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] is True
        assert "StandardOutPath" not in plist
        assert "ThrottleInterval" not in plist
