"""Process-wide tool allowlist for unattended runs (F-024 AC-002, D-011)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from openjarvis.agents._stubs import AgentResult, ToolUsingAgent
from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.security.runtime import execute_secured_tool
from openjarvis.security.tool_allowlist import (
    blocked_reason,
    filter_permitted,
    restrict_process_tools,
    tool_permitted,
)
from openjarvis.tools import _stubs
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec

_REASON = "not in test.allowed_tools"


@pytest.fixture(autouse=True)
def _unrestricted_after_test():
    restrict_process_tools(None)
    yield
    restrict_process_tools(None)


class _Tool(BaseTool):
    """Records whether ``execute`` ran."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.calls = 0

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name=self._name, description=f"{self._name} tool")

    def execute(self, **params: Any) -> ToolResult:
        self.calls += 1
        return ToolResult(tool_name=self._name, content="ran", success=True)


def _call(name: str) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=json.dumps({}))


class TestModuleApi:
    def test_unrestricted_by_default(self):
        assert tool_permitted("shell_exec")

    def test_restriction_permits_only_listed_names(self):
        restrict_process_tools(["digest_collect"])

        assert tool_permitted("digest_collect")
        assert not tool_permitted("shell_exec")

    def test_empty_restriction_permits_nothing(self):
        restrict_process_tools([])

        assert not tool_permitted("digest_collect")

    def test_none_lifts_the_restriction(self):
        restrict_process_tools([])
        restrict_process_tools(None)

        assert tool_permitted("shell_exec")
        assert blocked_reason("shell_exec") is None

    def test_blocked_reason_is_the_callers_reason(self):
        restrict_process_tools(["digest_collect"], reason=_REASON)

        assert blocked_reason("shell_exec") == _REASON
        assert blocked_reason("digest_collect") is None

    def test_blocked_reason_has_a_generic_default(self):
        restrict_process_tools([])

        assert blocked_reason("shell_exec") == "not in this process tool allowlist"

    def test_filter_permitted_keeps_order_by_spec_name(self):
        tools = [_Tool("b"), _Tool("x"), _Tool("a")]
        restrict_process_tools({"a", "b"})

        assert [t.spec.name for t in filter_permitted(tools)] == ["b", "a"]

    def test_filter_permitted_unrestricted_returns_all(self):
        tools = [_Tool("a"), _Tool("b")]

        assert filter_permitted(tools) == tools


class TestToolExecutor:
    def test_disallowed_tool_is_denied_without_executing(self, caplog):
        tool = _Tool("shell_exec")
        restrict_process_tools(["digest_collect"], reason=_REASON)

        with caplog.at_level(logging.WARNING, logger="openjarvis.tools._stubs"):
            result = ToolExecutor([tool]).execute(_call("shell_exec"))

        assert result.success is False
        assert result.content == f"Tool 'shell_exec' blocked: {_REASON}"
        assert tool.calls == 0
        assert any(_REASON in m for m in caplog.messages)

    def test_block_is_published_as_capability_denied(self):
        bus = EventBus(record_history=True)
        restrict_process_tools(["digest_collect"], reason=_REASON)
        executor = ToolExecutor([_Tool("shell_exec")], bus=bus, agent_id="digest")

        executor.execute(_call("shell_exec"))

        (event,) = [
            e for e in bus.history if e.event_type is EventType.CAPABILITY_DENIED
        ]
        assert event.data == {
            "agent_id": "digest",
            "tool": "shell_exec",
            "reason": _REASON,
        }

    def test_permitted_call_publishes_no_denial(self):
        bus = EventBus(record_history=True)
        restrict_process_tools(["digest_collect"], reason=_REASON)
        executor = ToolExecutor([_Tool("digest_collect")], bus=bus, agent_id="d")

        executor.execute(_call("digest_collect"))

        assert bus.history
        assert all(e.event_type is not EventType.CAPABILITY_DENIED for e in bus.history)

    def test_block_is_audited_as_tool_blocked(self, tmp_path):
        from openjarvis.security.audit import AuditLogger
        from openjarvis.security.types import SecurityEventType

        bus = EventBus()
        audit = AuditLogger(db_path=tmp_path / "audit.db", bus=bus)
        restrict_process_tools([], reason=_REASON)

        ToolExecutor([_Tool("shell_exec")], bus=bus, agent_id="digest").execute(
            _call("shell_exec")
        )

        blocked = audit.query(event_type=SecurityEventType.TOOL_BLOCKED.value)
        audit.close()
        assert [e.content_preview for e in blocked] == ["tool=shell_exec agent=digest"]
        assert blocked[0].action_taken == "capability_denied"

    def test_executor_names_no_process_or_config_key(self):
        source = Path(_stubs.__file__).read_text(encoding="utf-8")

        assert "scheduler" not in source
        assert "unattended" not in source

    def test_allowed_tool_executes(self):
        tool = _Tool("digest_collect")
        restrict_process_tools(["digest_collect"])

        result = ToolExecutor([tool]).execute(_call("digest_collect"))

        assert result.success is True
        assert tool.calls == 1

    def test_unrestricted_changes_nothing(self):
        tool = _Tool("shell_exec")

        result = ToolExecutor([tool]).execute(_call("shell_exec"))

        assert result.success is True
        assert tool.calls == 1


class TestDirectToolPaths:
    def test_execute_secured_tool_is_denied(self):
        tool = _Tool("web_search")
        restrict_process_tools([])

        result = execute_secured_tool(tool, {}, agent_id="native_openhands")

        assert result.success is False
        assert tool.calls == 0

    def test_agent_own_tools_are_gated(self):
        # ProactiveAgent-style: the agent builds its own tool list after the
        # orchestrator filtered its kwargs, so only the executor can stop it.
        class _SelfToolingAgent(ToolUsingAgent):
            agent_id = "self_tooling"

            def run(self, input, context=None, **kwargs):
                result = self._executor.execute(_call("channel_send"))
                return AgentResult(content=result.content)

        send = _Tool("channel_send")
        restrict_process_tools([], reason=_REASON)
        agent = _SelfToolingAgent(MagicMock(), "m", tools=[send], max_turns=1)

        reply = agent.run("send it")

        assert _REASON in reply.content
        assert send.calls == 0
