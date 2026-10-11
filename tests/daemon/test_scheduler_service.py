"""Scheduler LaunchAgent install/uninstall/status and the lock (F-024 AC-005).

Every path is under tmp_path and launchctl is a recording fake.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

from openjarvis.daemon import scheduler_service as service


class _Launchctl:
    """Records argv; ``fail_on`` makes that subcommand raise like check=True."""

    def __init__(self, returncode=0, fail_on=None):
        self.returncode = returncode
        self.fail_on = fail_on
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.fail_on and argv[1] == self.fail_on and kwargs.get("check"):
            raise subprocess.CalledProcessError(5, argv)
        return subprocess.CompletedProcess(argv, self.returncode)


@pytest.fixture()
def paths(tmp_path):
    return service.SchedulerServicePaths(
        plist=tmp_path / "LaunchAgents" / f"{service.SCHEDULER_LABEL}.plist",
        log_dir=tmp_path / "home" / "logs",
        lock=tmp_path / "home" / "scheduler.lock",
    )


class TestPaths:
    def test_default_logs_and_lock_live_in_openjarvis_home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))

        default = service.SchedulerServicePaths.default()

        assert default.log_dir == tmp_path / "logs"
        assert default.lock == tmp_path / "scheduler.lock"
        assert default.plist.name == "com.openjarvis.scheduler.plist"
        assert default.plist.parent.name == "LaunchAgents"
        assert default.stdout_log == tmp_path / "logs" / "scheduler.out.log"
        assert default.stderr_log == tmp_path / "logs" / "scheduler.err.log"


class TestInstall:
    def test_writes_plist_with_service_fields(self, paths):
        returned = service.install(paths, run=_Launchctl())

        plist = plistlib.loads(paths.plist.read_bytes())
        assert returned == paths.plist
        assert plist["Label"] == service.SCHEDULER_LABEL
        assert plist["RunAtLoad"] is True
        # Crash-only restarts: a clean exit (e.g. lock already held) stays down.
        assert plist["KeepAlive"] == {"SuccessfulExit": False}
        assert plist["ThrottleInterval"] == 30
        assert Path(plist["ProgramArguments"][0]).is_absolute()
        assert plist["ProgramArguments"][-2:] == ["scheduler", "start"]
        assert plist["StandardOutPath"] == str(paths.stdout_log)
        assert plist["StandardErrorPath"] == str(paths.stderr_log)
        assert "EnvironmentVariables" not in plist
        assert paths.log_dir.is_dir()

    def test_plist_carries_no_secret_from_environment(self, paths, monkeypatch):
        monkeypatch.setenv("CARTESIA_API_KEY", "ck-should-not-leak")

        service.install(paths, run=_Launchctl())

        assert "ck-should-not-leak" not in paths.plist.read_text()

    def test_reloads_service_via_launchctl(self, paths):
        launchctl = _Launchctl()

        service.install(paths, run=launchctl)

        domain = f"gui/{os.getuid()}"
        (bootout, bootout_kw), (bootstrap, bootstrap_kw) = launchctl.calls
        assert bootout == [
            "launchctl",
            "bootout",
            f"{domain}/{service.SCHEDULER_LABEL}",
        ]
        assert bootout_kw["check"] is False
        assert bootstrap == ["launchctl", "bootstrap", domain, str(paths.plist)]
        assert bootstrap_kw["check"] is True

    def test_refused_bootstrap_propagates(self, paths):
        launchctl = _Launchctl(fail_on="bootstrap")

        with pytest.raises(subprocess.CalledProcessError):
            service.install(paths, run=launchctl, sleep=lambda _s: None)

        bootstraps = [argv for argv, _ in launchctl.calls if argv[1] == "bootstrap"]
        assert len(bootstraps) == service._BOOTSTRAP_ATTEMPTS

    def test_bootstrap_retries_while_old_job_is_still_unloading(self, paths):
        # Real launchd: bootstrap right after bootout fails with exit 5 until
        # the old job is gone; giving up would leave no scheduler running.
        launchctl = _Launchctl(fail_on="bootstrap")
        waits = []

        def sleep(seconds):
            waits.append(seconds)
            launchctl.fail_on = None

        service.install(paths, run=launchctl, sleep=sleep)

        bootstraps = [argv for argv, _ in launchctl.calls if argv[1] == "bootstrap"]
        assert len(bootstraps) == 2
        assert len(waits) == 1


class TestUninstall:
    def test_removes_plist(self, paths):
        launchctl = _Launchctl()
        service.install(paths, run=launchctl)

        assert service.uninstall(paths, run=launchctl) is True
        assert not paths.plist.exists()
        assert launchctl.calls[-1][0][1] == "bootout"

    def test_not_installed_returns_false(self, paths):
        launchctl = _Launchctl()

        assert service.uninstall(paths, run=launchctl) is False
        assert [argv[1] for argv, _ in launchctl.calls] == ["bootout"]


class TestStatus:
    def test_nothing_installed(self, paths):
        state = service.status(paths, run=_Launchctl(returncode=113))

        assert state == {"installed": False, "loaded": False, "running": False}

    def test_installed_loaded_and_running(self, paths):
        service.install(paths, run=_Launchctl())
        lock = service.acquire_lock(paths.lock)
        try:
            state = service.status(paths, run=_Launchctl(returncode=0))
        finally:
            lock.close()

        assert state == {"installed": True, "loaded": True, "running": True}

    def test_missing_launchctl_reports_not_loaded(self, paths):
        def _no_launchctl(argv, **kwargs):
            raise FileNotFoundError("launchctl")

        assert service.status(paths, run=_no_launchctl)["loaded"] is False


class TestLock:
    def test_second_acquire_is_refused(self, paths):
        first = service.acquire_lock(paths.lock)
        try:
            with pytest.raises(service.SchedulerAlreadyRunning):
                service.acquire_lock(paths.lock)
        finally:
            first.close()

    def test_lock_is_reusable_after_release(self, paths):
        service.acquire_lock(paths.lock).close()

        second = service.acquire_lock(paths.lock)
        second.close()

        assert paths.lock.read_text() == f"{os.getpid()}\n"

    def test_refused_attempt_keeps_holder_pid(self, paths):
        first = service.acquire_lock(paths.lock)
        try:
            with pytest.raises(service.SchedulerAlreadyRunning):
                service.acquire_lock(paths.lock)
            assert paths.lock.read_text() == f"{os.getpid()}\n"
        finally:
            first.close()

    def test_is_lock_held(self, paths):
        assert service.is_lock_held(paths.lock) is False
        held = service.acquire_lock(paths.lock)
        try:
            assert service.is_lock_held(paths.lock) is True
        finally:
            held.close()
        assert service.is_lock_held(paths.lock) is False


class TestProgramArgs:
    def test_jarvis_entry_point_is_made_absolute(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["jarvis", "scheduler", "start"])

        args = service.program_args()

        assert args == [str(Path("jarvis").absolute()), "scheduler", "start"]

    def test_falls_back_to_jarvis_on_path(self, monkeypatch, tmp_path):
        found = tmp_path / "bin" / "jarvis"
        monkeypatch.setattr(sys, "argv", ["pytest"])
        monkeypatch.setattr(service.shutil, "which", lambda name: str(found))

        assert service.program_args() == [str(found), "scheduler", "start"]

    def test_falls_back_to_module_invocation(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["pytest"])
        monkeypatch.setattr(service.shutil, "which", lambda name: None)

        args = service.program_args()

        assert args == [sys.executable, "-m", "openjarvis.cli", "scheduler", "start"]
        assert Path(args[0]).is_absolute()
