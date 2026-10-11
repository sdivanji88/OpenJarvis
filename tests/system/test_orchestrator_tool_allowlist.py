"""QueryOrchestrator withholds tools the process allowlist blocks (F-024 AC-002)."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from openjarvis.agents._stubs import AgentResult
from openjarvis.core.config import JarvisConfig
from openjarvis.core.events import EventBus
from openjarvis.core.registry import AgentRegistry, ToolRegistry
from openjarvis.security.tool_allowlist import restrict_process_tools
from openjarvis.system import QueryOrchestrator


@pytest.fixture(autouse=True)
def _unrestricted_after_test():
    yield
    restrict_process_tools(None)


def _tool(name: str) -> Any:
    return SimpleNamespace(spec=SimpleNamespace(name=name))


class _RecordingAgent:
    """Tool-accepting agent that records the tool names it was built with."""

    accepts_tools = True
    seen: List[List[str]] = []

    def __init__(self, engine, model, **kwargs):
        type(self).seen.append([t.spec.name for t in kwargs.get("tools") or []])

    def run(self, query, context=None):
        return AgentResult(content="ok")


@dataclass
class _FakeSystem:
    config: JarvisConfig = field(default_factory=JarvisConfig)
    bus: EventBus = field(default_factory=EventBus)
    engine: Any = None
    engine_key: str = "fake"
    model: str = "fake-model"
    agent_name: str = ""
    tools: List[Any] = field(default_factory=list)
    memory_backend: Optional[Any] = None
    capability_policy: Optional[Any] = None
    session_store: Optional[Any] = None
    trace_store: Optional[Any] = None
    trace_collector: Optional[Any] = None


@pytest.fixture()
def seen():
    _RecordingAgent.seen = []
    for name in ("morning_digest", "simple_tools"):
        AgentRegistry.register_value(name, _RecordingAgent)
    return _RecordingAgent.seen


def _ask(system: _FakeSystem, agent: str, tools: Optional[List[str]] = None) -> None:
    QueryOrchestrator(system).ask("go", context=False, agent=agent, tools=tools)


class TestDigestInjectedTools:
    def test_allowlist_withholds_injected_tts(self, seen):
        restrict_process_tools({"digest_collect"})

        _ask(_FakeSystem(), "morning_digest")

        assert seen == [["digest_collect"]]

    def test_allowlist_keeps_both_digest_tools(self, seen):
        restrict_process_tools({"digest_collect", "text_to_speech"})

        _ask(_FakeSystem(tools=[_tool("shell_exec")]), "morning_digest")

        assert seen == [["digest_collect", "text_to_speech"]]

    def test_empty_allowlist_withholds_everything(self, seen):
        restrict_process_tools([])

        _ask(_FakeSystem(tools=[_tool("calculator")]), "morning_digest")

        assert seen == [[]]

    def test_no_allowlist_leaves_digest_tools_unchanged(self, seen):
        _ask(_FakeSystem(tools=[_tool("calculator")]), "morning_digest")

        assert seen == [["digest_collect", "text_to_speech", "calculator"]]


class TestTaskNamedTools:
    def test_task_named_tools_are_filtered(self, seen):
        ToolRegistry.register_value("calculator", lambda: _tool("calculator"))
        ToolRegistry.register_value("shell_exec", lambda: _tool("shell_exec"))
        restrict_process_tools({"calculator"})

        _ask(_FakeSystem(), "simple_tools", tools=["calculator", "shell_exec"])

        assert seen == [["calculator"]]

    def test_system_default_tools_are_filtered(self, seen):
        restrict_process_tools({"web_search"})
        system = _FakeSystem(tools=[_tool("calculator"), _tool("web_search")])

        _ask(system, "simple_tools")

        assert seen == [["web_search"]]

    def test_no_allowlist_leaves_tools_unchanged(self, seen):
        system = _FakeSystem(tools=[_tool("calculator"), _tool("web_search")])

        _ask(system, "simple_tools")

        assert seen == [["calculator", "web_search"]]

    def test_list_allowlist_is_honoured_not_ignored(self, seen):
        restrict_process_tools(["nothing"])

        _ask(_FakeSystem(tools=[_tool("calculator")]), "simple_tools")

        assert seen == [[]]
