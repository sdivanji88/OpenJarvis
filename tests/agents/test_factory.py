"""Tests for the agent factory that applies the sandbox runtime."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import pytest

from openjarvis.agents import factory
from openjarvis.agents._stubs import AgentResult, BaseAgent
from openjarvis.agents.factory import build_agent
from openjarvis.core.config import JarvisConfig
from openjarvis.sandbox.runner import SandboxedAgent


class EchoAgent(BaseAgent):
    agent_id = "echo"

    def __init__(self, engine: Any, model: str, **kwargs: Any) -> None:
        super().__init__(engine, model)
        self.kwargs = kwargs

    def run(self, input: str, context: Any = None, **kwargs: Any) -> AgentResult:
        return AgentResult(content=f"host:{input}", turns=1)


class RecordingRunner:
    def __init__(self) -> None:
        self.requests: List[Dict[str, Any]] = []

    def run(self, input_data: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
        self.requests.append(input_data)
        return {"content": "sandboxed"}


def openshell_config() -> JarvisConfig:
    config = JarvisConfig()
    config.sandbox.runtime = "openshell"
    return config


@pytest.fixture
def runner(monkeypatch) -> RecordingRunner:
    runner = RecordingRunner()
    monkeypatch.setattr(factory, "shared_runner", lambda sandbox: runner)
    return runner


def test_no_code_constructs_registry_agents_outside_the_factory():
    src = Path(factory.__file__).resolve().parents[1]
    pattern = re.compile(r"\b(agent_cls|execution_cls|execution_agent_cls)\(")
    offenders = [
        f"{path.relative_to(src)}:{lineno}"
        for path in src.rglob("*.py")
        if path.name != "factory.py"
        for lineno, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


def test_default_runtime_returns_the_plain_agent():
    agent = build_agent(EchoAgent, None, "m", config=JarvisConfig(), extra=1)
    assert isinstance(agent, EchoAgent)
    assert agent.kwargs == {"extra": 1}


def test_openshell_runtime_wraps_the_agent(runner):
    agent = build_agent(EchoAgent, None, "m", config=openshell_config())
    assert isinstance(agent, SandboxedAgent)
    assert isinstance(agent._wrapped_agent, EchoAgent)


def test_wrapped_agent_runs_in_the_sandbox_not_on_the_host(runner):
    agent = build_agent(EchoAgent, None, "m", config=openshell_config())
    result = agent.run("hello")
    assert result.content == "sandboxed"
    assert runner.requests[0]["agent_id"] == "echo"
    assert runner.requests[0]["prompt"] == "hello"
