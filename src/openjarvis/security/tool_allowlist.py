"""Process-wide tool allowlist for unattended processes (D-011).

A process that runs agents with nobody watching (the scheduler daemon) calls
``restrict_process_tools`` once at startup. The restriction is enforced in
``ToolExecutor.execute`` — the gate every OpenJarvis tool call passes through,
including tools an agent constructs for itself and ``execute_secured_tool`` —
and is also used to stop offering disallowed tools to the model. The caller
supplies the refusal reason, so the executor can report *why* without knowing
which process or config key imposed the restriction.

It is process-wide rather than a ``ContextVar`` on purpose: the daemon runs
only unattended work, and tools may execute on worker threads, which would not
inherit a context variable and would silently run unrestricted (fail-open).
Not covered, so guarded only by ``scheduler.allowed_agents``: agents that drive
external CLIs with their own tools (claude_code, opencode) and the hybrid
agents (``agents/hybrid``, e.g. ``tavily_search_context``), which call tools
directly instead of through the executor. Names are matched as the agent
exposes them to the model, so a tool offered under another name is checked
under that name.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

_DEFAULT_REASON = "not in this process tool allowlist"

_lock = threading.Lock()
# (allowed names, refusal reason); None = unrestricted. Swapped as one tuple so
# readers never see a new list paired with an old reason.
_restriction: Optional[Tuple[frozenset[str], str]] = None


def restrict_process_tools(
    names: Optional[Iterable[str]], *, reason: str = _DEFAULT_REASON
) -> None:
    """Allow only *names* for the rest of this process; ``None`` lifts it.

    An empty iterable allows no tools at all. *reason* is reported for every
    refused call.
    """
    global _restriction
    restriction = None if names is None else (frozenset(names), reason)
    with _lock:
        _restriction = restriction
    if restriction is None:
        logger.info("Process tool allowlist cleared (unrestricted)")
    else:
        logger.info("Process tool allowlist: %s", sorted(restriction[0]))


def blocked_reason(name: str) -> Optional[str]:
    """Why a tool called *name* may not execute here, or ``None`` if it may."""
    restriction = _restriction
    if restriction is None or name in restriction[0]:
        return None
    return restriction[1]


def tool_permitted(name: str) -> bool:
    """Whether a tool called *name* may execute in this process."""
    return blocked_reason(name) is None


def filter_permitted(tools: List[Any]) -> List[Any]:
    """The tools (by ``spec.name``) that may execute; all of them if unrestricted."""
    return [t for t in tools if blocked_reason(t.spec.name) is None]


__all__ = [
    "blocked_reason",
    "filter_permitted",
    "restrict_process_tools",
    "tool_permitted",
]
