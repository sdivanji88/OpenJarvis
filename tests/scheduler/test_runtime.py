"""OnDemandSystem — the system the scheduler daemon runs tasks on (F-024)."""

from __future__ import annotations

import os

import pytest

from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus
from openjarvis.scheduler import runtime
from openjarvis.scheduler.runtime import OnDemandSystem


class _FakeSystem:
    def __init__(self, result=None, exc=None):
        self.result = result
        self.exc = exc
        self.asks = []
        self.closed = False

    def ask(self, prompt, **kwargs):
        self.asks.append((prompt, kwargs))
        if self.exc is not None:
            raise self.exc
        return self.result

    def close(self):
        self.closed = True


class _Builder:
    """``build`` callable that hands out a fresh fake system per call."""

    def __init__(self, **system_kwargs):
        self.system_kwargs = system_kwargs
        self.built = []

    def __call__(self):
        system = _FakeSystem(**self.system_kwargs)
        self.built.append(system)
        return system


@pytest.fixture()
def no_cartesia_env(monkeypatch):
    # setenv first so monkeypatch records the original and undoes the
    # os.environ write inject_credentials makes behind its back.
    monkeypatch.setenv("CARTESIA_API_KEY", "placeholder")
    monkeypatch.delenv("CARTESIA_API_KEY")


@pytest.fixture()
def creds(tmp_path):
    return tmp_path / "missing-credentials.toml"


class TestAsk:
    @pytest.mark.parametrize(
        "result",
        [{"content": "good morning", "usage": {}}, "plain", None],
        ids=["dict", "str", "none"],
    )
    def test_returns_raw_result(self, creds, result):
        build = _Builder(result=result)

        reply = OnDemandSystem(credentials_path=creds, build=build).ask("hi")

        assert reply == result

    def test_forwards_prompt_and_kwargs(self, creds):
        build = _Builder(result={"content": ""})

        OnDemandSystem(credentials_path=creds, build=build).ask(
            "brief", agent="morning_digest", tools=None
        )

        assert build.built[0].asks == [
            ("brief", {"agent": "morning_digest", "tools": None})
        ]

    def test_builds_fresh_system_per_ask(self, creds):
        build = _Builder(result={"content": "x"})
        system = OnDemandSystem(credentials_path=creds, build=build)

        system.ask("one")
        system.ask("two")

        assert len(build.built) == 2
        assert build.built[0] is not build.built[1]

    def test_closes_system_after_success(self, creds):
        build = _Builder(result={"content": "x"})

        OnDemandSystem(credentials_path=creds, build=build).ask("q")

        assert build.built[0].closed is True

    def test_closes_system_when_ask_raises(self, creds):
        build = _Builder(exc=ConnectionError("ollama down"))
        system = OnDemandSystem(credentials_path=creds, build=build)

        with pytest.raises(ConnectionError):
            system.ask("q")

        assert build.built[0].closed is True

    def test_error_result_is_passed_through_for_the_scheduler(self, creds):
        error = {"content": "Unknown agent: nope", "error": True}
        build = _Builder(result=error)

        reply = OnDemandSystem(credentials_path=creds, build=build).ask("q")

        assert reply == error
        assert build.built[0].closed is True

    def test_config_cache_cleared_before_each_build(self, creds, monkeypatch):
        order = []

        class _Loader:
            @staticmethod
            def cache_clear():
                order.append("cache_clear")

        def _build():
            order.append("build")
            return _FakeSystem(result={"content": ""})

        monkeypatch.setattr(runtime, "load_config", _Loader)

        OnDemandSystem(credentials_path=creds, build=_build).ask("q")

        assert order == ["cache_clear", "build"]


class TestCredentials:
    def test_credentials_file_reaches_environment_before_build(
        self, tmp_path, no_cartesia_env
    ):
        path = tmp_path / "credentials.toml"
        path.write_text('[text_to_speech]\nCARTESIA_API_KEY = "ck-from-file"\n')
        seen = {}

        def _build():
            seen["key"] = os.environ.get("CARTESIA_API_KEY")
            return _FakeSystem(result={"content": ""})

        OnDemandSystem(credentials_path=path, build=_build).ask("q")

        assert seen["key"] == "ck-from-file"

    def test_default_path_is_credentials_toml_in_openjarvis_home(
        self, tmp_path, monkeypatch, no_cartesia_env
    ):
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))
        (tmp_path / "credentials.toml").write_text(
            '[text_to_speech]\nCARTESIA_API_KEY = "ck-home"\n'
        )
        seen = {}

        def _build():
            seen["key"] = os.environ.get("CARTESIA_API_KEY")
            return _FakeSystem(result={"content": ""})

        OnDemandSystem(build=_build).ask("q")

        assert seen["key"] == "ck-home"


class TestDefaultBuild:
    def test_default_build_disables_task_scheduler(self, monkeypatch):
        calls = []

        class _RecordingBuilder:
            def __init__(self, config):
                calls.append(("init", type(config).__name__))

            def scheduler(self, enabled):
                calls.append(("scheduler", enabled))
                return self

            def event_bus(self, bus):
                calls.append(("event_bus", type(bus).__name__))
                return self

            def build(self):
                calls.append(("build",))
                return "system"

        monkeypatch.setattr("openjarvis.system.SystemBuilder", _RecordingBuilder)

        assert runtime._build_system() == "system"
        assert ("scheduler", False) in calls
        assert ("event_bus", "EventBus") in calls

    def test_scheduler_false_wires_no_task_scheduler(self):
        from openjarvis.system import SystemBuilder

        config = JarvisConfig()
        config.scheduler.enabled = True

        builder = SystemBuilder(config).scheduler(False)

        assert builder._setup_scheduler(config, EventBus()) == (None, None)
