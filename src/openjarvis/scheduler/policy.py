"""What an unattended scheduler may run, and when a run is too late to bother.

Scheduled tasks execute with nobody watching, so the daemon only runs agents
and offers tools the user listed in ``[scheduler]`` (D-011), and a task may
declare a grace window after which a late run is skipped as missed (D-012).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Union

from openjarvis.scheduler.store import RunOutcome

# Task-metadata key holding the late-run window in minutes. Only this module
# interprets it; task creators set it via this constant.
MISFIRE_GRACE_KEY = "misfire_grace_minutes"


def _names(value: Any) -> frozenset[str]:
    """Normalise a TOML array or comma-separated string to a set of names."""
    if value is None:
        return frozenset()
    items: Iterable[Any] = value.split(",") if isinstance(value, str) else value
    return frozenset(str(item).strip() for item in items if str(item).strip())


@dataclass(frozen=True)
class RunPolicy:
    """What an unattended scheduler may run.

    ``None`` means unrestricted (the library default, so operators and other
    in-process callers keep working); an empty frozenset means nothing is
    allowed (the config default for ``jarvis scheduler start``).

    The scheduler enforces ``allowed_agents`` itself. ``allowed_tools`` is
    enforced process-wide by ``security.tool_allowlist``, which the daemon
    sets at startup; the scheduler only reports it in the audit line.
    """

    allowed_agents: Optional[frozenset[str]] = None
    allowed_tools: Optional[frozenset[str]] = None

    @classmethod
    def from_config(cls, scheduler_cfg: Any) -> RunPolicy:
        """Deny-by-default policy from ``[scheduler]`` (missing keys allow nothing)."""
        return cls(
            allowed_agents=_names(getattr(scheduler_cfg, "allowed_agents", None)),
            allowed_tools=_names(getattr(scheduler_cfg, "allowed_tools", None)),
        )

    def admits(self, agent: str) -> bool:
        """Whether a task for *agent* may run."""
        return self.allowed_agents is None or agent in self.allowed_agents

    def permitted_tools(self, requested: list[str]) -> Union[list[str], str]:
        """Upper bound on the tools a run may see, for the audit log.

        ``"unrestricted"`` without a tool allowlist. Otherwise the requested
        tools that survive the allowlist, or — when the task requests none and
        the agent falls back to its default and injected tools — the whole
        allowlist.
        """
        if self.allowed_tools is None:
            return "unrestricted"
        if requested:
            return [t for t in requested if t in self.allowed_tools]
        return sorted(self.allowed_tools)


@dataclass(frozen=True)
class Misfire:
    """A run that is too late to bother with."""

    minutes_late: float
    grace_minutes: float

    @property
    def message(self) -> str:
        """Human-readable reason for the missed run."""
        return f"{self.minutes_late:.0f} min late (grace {self.grace_minutes:g})"


def _grace_minutes(task_metadata: dict) -> Optional[float]:
    raw = (task_metadata or {}).get(MISFIRE_GRACE_KEY)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        grace = float(raw)
    except (TypeError, ValueError):
        return None
    return grace if grace >= 0 else None


def missed_by(
    task_metadata: dict,
    scheduled_iso: Optional[str],
    now: datetime,
) -> Optional[Misfire]:
    """The misfire, if the run is later than the task's grace window.

    Returns ``None`` — meaning the run should proceed — when the task has no
    (or an invalid) grace setting, the scheduled time is missing or
    unparsable, or the run is within the window. Naive times are taken as UTC.
    """
    grace = _grace_minutes(task_metadata)
    if grace is None or not scheduled_iso:
        return None
    try:
        scheduled = datetime.fromisoformat(scheduled_iso)
    except (TypeError, ValueError):
        return None
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    late = (now - scheduled).total_seconds() / 60
    return Misfire(minutes_late=late, grace_minutes=grace) if late > grace else None


def audit_line(
    task_id: str,
    agent: str,
    outcome: RunOutcome,
    requested_tools: list[str],
    policy: RunPolicy,
    duration_s: float,
) -> str:
    """One-line record of a scheduled run.

    Deliberately excludes prompt, result, and error text: those may carry
    personal data or secrets and belong in the run log, not the service log.
    """
    return (
        f"scheduled run task={task_id} agent={agent} outcome={outcome} "
        f"requested_tools={sorted(requested_tools)} "
        f"permitted_tools={policy.permitted_tools(requested_tools)} "
        f"duration_s={duration_s:.1f}"
    )


__all__ = ["MISFIRE_GRACE_KEY", "Misfire", "RunPolicy", "audit_line", "missed_by"]
