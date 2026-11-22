"""``jarvis scheduler start|status`` (F-024 AC-001, AC-002, AC-005).

launchctl, the service paths, the store, and the shutdown wait are patched via
the module's seams; OPENJARVIS_HOME is a per-test tmp dir.
"""

from __future__ import annotations

import plistlib
import stat
import subprocess

import pytest
from click.testing import CliRunner

from openjarvis.cli import scheduler_service_cmd as cmd
from openjarvis.cli.scheduler_cmd import scheduler
from openjarvis.core.config import load_config
from openjarvis.daemon import scheduler_service as service
from openjarvis.scheduler.policy import RunPolicy
from openjarvis.scheduler.runtime import OnDemandSystem
from openjarvis.security.tool_allowlist import (
    blocked_reason,
    restrict_process_tools,
    tool_permitted,
)

_ALLOW_TOML = (
    "[scheduler]\n"
    'allowed_agents = ["morning_digest"]\n'
    'allowed_tools = ["digest_collect", "text_to_speech"]\n'
)


class _Launchctl:
    def __init__(self, returncode=0):
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(argv, self.returncode)


@pytest.fixture(autouse=True)
def _unrestricted_after_test():
    # Plain `start` restricts the whole process; don't leak into other tests.
    restrict_process_tools(None)
    yield
    restrict_process_tools(None)


@pytest.fixture(autouse=True)
def _no_shell_cartesia_key(monkeypatch):
    # setenv first so monkeypatch also undoes save_credential's os.environ write.
    monkeypatch.setenv("CARTESIA_API_KEY", "placeholder")
    monkeypatch.delenv("CARTESIA_API_KEY")


@pytest.fixture()
def home(tmp_path, monkeypatch):
    path = tmp_path / "home"
    path.mkdir()
    monkeypatch.setenv("OPENJARVIS_HOME", str(path))
    load_config.cache_clear()
    return path


@pytest.fixture()
def paths(tmp_path, home, monkeypatch):
    p = service.SchedulerServicePaths(
        plist=tmp_path / "LaunchAgents" / f"{service.SCHEDULER_LABEL}.plist",
        log_dir=home / "logs",
        lock=home / "scheduler.lock",
    )
    monkeypatch.setattr(cmd, "_paths", lambda: p)
    return p


@pytest.fixture()
def launchctl(monkeypatch):
    fake = _Launchctl()
    monkeypatch.setattr(cmd, "_launchctl_run", fake)
    return fake


@pytest.fixture()
def darwin(monkeypatch, tmp_path):
    monkeypatch.setattr(cmd.platform, "system", lambda: "Darwin")
    # An empty cwd means no checkout persona is offered unless a test adds one.
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


@pytest.fixture()
def cartesia_env(monkeypatch):
    monkeypatch.setenv("CARTESIA_API_KEY", "ck-from-shell")
    return "ck-from-shell"


def _invoke(*args, input=None):
    return CliRunner().invoke(scheduler, list(args), input=input)


class TestInstall:
    def test_accepting_copies_key_to_owner_only_credentials(
        self, home, paths, launchctl, darwin, cartesia_env
    ):
        result = _invoke("start", "--install", input="y\n")

        creds = home / "credentials.toml"
        assert result.exit_code == 0, result.output
        assert cartesia_env in creds.read_text()
        assert stat.S_IMODE(creds.stat().st_mode) == 0o600
        assert cartesia_env not in paths.plist.read_text()
        assert f"Installed {paths.plist}" in result.output

    def test_plist_is_written_with_service_fields(self, home, paths, launchctl, darwin):
        result = _invoke("start", "--install")

        plist = plistlib.loads(paths.plist.read_bytes())
        assert result.exit_code == 0, result.output
        assert plist["RunAtLoad"] is True
        assert plist["KeepAlive"] == {"SuccessfulExit": False}
        assert plist["ProgramArguments"][0].startswith("/")
        assert plist["StandardOutPath"] == str(home / "logs" / "scheduler.out.log")
        assert "EnvironmentVariables" not in plist
        assert [argv[1] for argv in launchctl.calls] == ["bootout", "bootstrap"]

    @pytest.mark.parametrize("answer", ["n\n", "\n"], ids=["no", "default"])
    def test_declining_writes_no_credentials(
        self, home, paths, launchctl, darwin, cartesia_env, answer
    ):
        result = _invoke("start", "--install", input=answer)

        assert result.exit_code == 0, result.output
        assert not (home / "credentials.toml").exists()
        assert paths.plist.exists()

    def test_existing_key_is_not_offered_again(
        self, home, paths, launchctl, darwin, cartesia_env
    ):
        creds = home / "credentials.toml"
        creds.write_text('[text_to_speech]\nCARTESIA_API_KEY = "ck-saved"\n')

        result = _invoke("start", "--install")

        assert result.exit_code == 0, result.output
        assert "Copy CARTESIA_API_KEY" not in result.output
        assert "ck-saved" in creds.read_text()

    def test_key_not_offered_for_other_tts_backends(
        self, home, paths, launchctl, darwin, cartesia_env
    ):
        (home / "config.toml").write_text('[digest]\ntts_backend = "kokoro"\n')

        result = _invoke("start", "--install", input="y\n")

        assert result.exit_code == 0, result.output
        assert "Copy CARTESIA_API_KEY" not in result.output
        assert not (home / "credentials.toml").exists()

    def test_persona_is_copied_into_config_dir(self, home, paths, launchctl, darwin):
        persona_dir = darwin / "configs/openjarvis/prompts/personas"
        persona_dir.mkdir(parents=True)
        (persona_dir / "jarvis.md").write_text("You are Jarvis.")

        result = _invoke("start", "--install", input="\n")

        copied = home / "prompts" / "personas" / "jarvis.md"
        assert result.exit_code == 0, result.output
        assert copied.read_text() == "You are Jarvis."

    def test_persona_name_cannot_escape_persona_dirs(self, home, darwin):
        persona_dir = darwin / "configs/openjarvis/prompts/personas"
        persona_dir.mkdir(parents=True)
        (persona_dir.parent / "evil.md").write_text("outside")

        cmd._offer_persona_copy("../evil")

        assert not (home / "prompts" / "evil.md").exists()
        assert not (home / "prompts" / "personas").exists()

    def test_warns_when_allowlists_are_empty(self, home, paths, launchctl, darwin):
        result = _invoke("start", "--install")

        assert "scheduler.allowed_agents is empty" in result.output
        assert "scheduler.allowed_tools is empty" in result.output

    def test_non_darwin_refuses(self, home, paths, launchctl, monkeypatch):
        monkeypatch.setattr(cmd.platform, "system", lambda: "Linux")

        result = _invoke("start", "--install")

        assert result.exit_code == 1
        assert "macOS launchd only" in result.output
        assert not paths.plist.exists()
        assert launchctl.calls == []

    def test_launchctl_refusal_exits_1(self, home, paths, darwin, monkeypatch):
        def _refuse(argv, **kwargs):
            if kwargs.get("check"):
                raise subprocess.CalledProcessError(5, argv)
            return subprocess.CompletedProcess(argv, 0)

        monkeypatch.setattr(cmd, "_launchctl_run", _refuse)

        result = _invoke("start", "--install")

        assert result.exit_code == 1
        assert "launchctl refused the service (exit 5)" in result.output

    def test_install_and_uninstall_together_is_usage_error(self, paths, launchctl):
        result = _invoke("start", "--install", "--uninstall")

        assert result.exit_code == 2
        assert launchctl.calls == []


class TestUninstall:
    def test_removes_plist(self, paths, launchctl):
        paths.plist.parent.mkdir(parents=True)
        paths.plist.write_text("<plist/>")

        result = _invoke("start", "--uninstall")

        assert result.exit_code == 0, result.output
        assert not paths.plist.exists()
        assert f"Removed {paths.plist}" in result.output

    def test_service_commands_leave_tools_unrestricted(
        self, home, paths, launchctl, darwin
    ):
        (home / "config.toml").write_text(_ALLOW_TOML)

        _invoke("start", "--install")
        _invoke("start", "--uninstall")
        _invoke("status")

        assert tool_permitted("shell_exec")

    def test_not_installed_message(self, paths, launchctl):
        result = _invoke("start", "--uninstall")

        assert result.exit_code == 0
        assert "was not installed" in result.output


class _RecordingScheduler:
    instances: list = []

    def __init__(self, store, system=None, **kwargs):
        self.store = store
        self.system = system
        self.kwargs = kwargs
        self.events = []
        type(self).instances.append(self)

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


class _RecordingAutoplay:
    attached: list = []

    def attach(self, bus):
        type(self).attached.append(bus)


class _FakeStore:
    closed = False

    def close(self):
        self.closed = True


@pytest.fixture()
def foreground(home, paths, monkeypatch):
    """Plain ``start`` with every side effect replaced by a recorder."""
    _RecordingScheduler.instances = []
    _RecordingAutoplay.attached = []
    store = _FakeStore()
    waits = []
    monkeypatch.setattr(cmd, "_open_store", lambda: store)
    monkeypatch.setattr(cmd, "_wait_for_shutdown", lambda: waits.append(True))
    monkeypatch.setattr(cmd, "_configure_logging", lambda verbose: None)
    monkeypatch.setattr(
        "openjarvis.scheduler.scheduler.TaskScheduler", _RecordingScheduler
    )
    monkeypatch.setattr(
        "openjarvis.agents.digest_playback.DigestAutoplay", _RecordingAutoplay
    )
    return {"store": store, "waits": waits}


class TestForeground:
    def test_builds_real_scheduler_from_config(self, home, paths, foreground):
        (home / "config.toml").write_text(_ALLOW_TOML)

        result = _invoke("start", "--poll-interval", "7")

        assert result.exit_code == 0, result.output
        (sched,) = _RecordingScheduler.instances
        policy = sched.kwargs["policy"]
        assert policy == RunPolicy(
            allowed_agents=frozenset({"morning_digest"}),
            allowed_tools=frozenset({"digest_collect", "text_to_speech"}),
        )
        assert isinstance(sched.system, OnDemandSystem)
        assert sched.store is foreground["store"]
        assert sched.kwargs["poll_interval"] == 7
        assert sched.events == ["start", "stop"]
        assert foreground["waits"] == [True]
        assert foreground["store"].closed is True

    def test_restricts_process_tools_to_config_allowlist(self, home, paths, foreground):
        (home / "config.toml").write_text(_ALLOW_TOML)

        result = _invoke("start")

        assert result.exit_code == 0, result.output
        assert tool_permitted("digest_collect")
        assert tool_permitted("text_to_speech")
        assert not tool_permitted("shell_exec")

    def test_refusals_cite_the_scheduler_config_key(self, home, paths, foreground):
        _invoke("start")

        reason = blocked_reason("shell_exec")
        assert reason == "not in scheduler.allowed_tools (unattended runs)"

    def test_default_config_permits_no_tools(self, home, paths, foreground):
        _invoke("start")

        assert not tool_permitted("digest_collect")

    def test_autoplay_listens_on_the_scheduler_bus(self, home, paths, foreground):
        result = _invoke("start")

        assert result.exit_code == 0, result.output
        (sched,) = _RecordingScheduler.instances
        assert _RecordingAutoplay.attached == [sched.kwargs["bus"]]

    def test_default_config_is_deny_by_default(self, home, paths, foreground):
        result = _invoke("start")

        (sched,) = _RecordingScheduler.instances
        assert result.exit_code == 0, result.output
        assert sched.kwargs["policy"] == RunPolicy(frozenset(), frozenset())

    def test_lock_released_after_shutdown(self, home, paths, foreground):
        _invoke("start")

        service.acquire_lock(paths.lock).close()

    def test_second_instance_exits_cleanly_without_running(
        self, home, paths, foreground
    ):
        held = service.acquire_lock(paths.lock)
        try:
            result = _invoke("start")
        finally:
            held.close()

        # Exit 0, so launchd's KeepAlive={SuccessfulExit: False} won't respawn it.
        assert result.exit_code == 0, result.output
        assert "A scheduler is already running" in result.output
        assert "nothing to do" in result.output
        assert _RecordingScheduler.instances == []


class TestStatus:
    def test_reports_not_installed(self, paths, monkeypatch):
        monkeypatch.setattr(cmd, "_launchctl_run", _Launchctl(returncode=113))

        result = _invoke("status")

        assert result.exit_code == 0
        assert "installed: no" in result.output
        assert "loaded: no" in result.output
        assert "running: no" in result.output
        assert str(paths.plist) in result.output

    def test_reports_running_service(self, paths, launchctl):
        paths.plist.parent.mkdir(parents=True)
        paths.plist.write_text("<plist/>")
        held = service.acquire_lock(paths.lock)
        try:
            result = _invoke("status")
        finally:
            held.close()

        assert "installed: yes" in result.output
        assert "loaded: yes" in result.output
        assert "running: yes" in result.output
