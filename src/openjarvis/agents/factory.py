"""The single place agents are constructed.

Every construction site goes through :func:`build_agent` so the sandbox
runtime cannot be bypassed by a code path that forgot to apply it.
"""

from __future__ import annotations

from typing import Any, Type

from openjarvis.agents._stubs import BaseAgent
from openjarvis.core.config import JarvisConfig
from openjarvis.sandbox.openshell_runner import shared_runner
from openjarvis.sandbox.runner import SandboxedAgent


def build_agent(
    agent_cls: Type[BaseAgent], *args: Any, config: JarvisConfig, **kwargs: Any
) -> BaseAgent:
    """Construct ``agent_cls`` and, under the OpenShell runtime, sandbox it."""
    agent = agent_cls(*args, **kwargs)
    runner = shared_runner(config.sandbox)
    if runner is None:
        return agent
    return SandboxedAgent(agent, runner, bus=getattr(agent, "_bus", None))


__all__ = ["build_agent"]
