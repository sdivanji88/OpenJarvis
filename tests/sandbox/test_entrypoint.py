"""Tests for the in-sandbox agent entrypoint."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from openjarvis.agents.simple import SimpleAgent
from openjarvis.core.registry import AgentRegistry
from openjarvis.sandbox.entrypoint import main
from openjarvis.sandbox.runner import ContainerRunner
from tests.agents.fake_engine import FakeEngine


@pytest.fixture(autouse=True)
def _register_simple_agent():
    AgentRegistry.register_value("simple", SimpleAgent)


def run_entrypoint(request, engine=None):
    stdin = io.StringIO(request if isinstance(request, str) else json.dumps(request))
    stdout, stderr = io.StringIO(), io.StringIO()
    engine = engine or FakeEngine([{"content": "answer"}])
    code = main(stdin=stdin, stdout=stdout, stderr=stderr, engine=engine)
    return code, stdout.getvalue(), stderr.getvalue()


def test_runs_the_requested_agent_and_prints_its_result():
    code, out, _ = run_entrypoint({"prompt": "hi", "agent_id": "simple", "model": "m"})
    assert code == 0
    assert ContainerRunner._parse_output(out)["content"] == "answer"


def test_sends_the_prompt_to_the_engine():
    engine = FakeEngine([{"content": "answer"}])
    run_entrypoint({"prompt": "what time is it", "agent_id": "simple"}, engine)
    assert "what time is it" in str(engine.last_messages)


def test_unknown_agent_exits_non_zero_with_a_message():
    code, out, err = run_entrypoint({"prompt": "hi", "agent_id": "nope"})
    assert code != 0
    assert "nope" in err
    assert out == ""


def test_invalid_json_exits_non_zero():
    code, _, err = run_entrypoint("not json")
    assert code != 0
    assert "request" in err.lower()


def test_agent_failure_exits_non_zero():
    class Broken(FakeEngine):
        def generate(self, *a, **kw):
            raise RuntimeError("engine down")

    code, _, err = run_entrypoint({"prompt": "hi", "agent_id": "simple"}, Broken([]))
    assert code != 0
    assert "engine down" in err


def test_runs_in_the_requested_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path.parent)
    seen = {}

    class Recording(FakeEngine):
        def generate(self, *a, **kw):
            seen["cwd"] = Path.cwd()
            return super().generate(*a, **kw)

    run_entrypoint(
        {"prompt": "hi", "agent_id": "simple", "_workspace": str(tmp_path)},
        Recording([{"content": "ok"}]),
    )
    assert seen["cwd"] == tmp_path


@pytest.mark.parametrize("missing", ["prompt", "agent_id"])
def test_missing_fields_exit_non_zero(missing):
    request = {"prompt": "hi", "agent_id": "simple"}
    del request[missing]
    code, _, err = run_entrypoint(request)
    assert code != 0
    assert missing in err
