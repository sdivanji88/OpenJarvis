"""Rich markup for scheduler run outcomes, shared by the log commands."""

from __future__ import annotations

from openjarvis.scheduler.store import RunOutcome

_COLOURS = {RunOutcome.SUCCESS: "green", RunOutcome.FAILED: "red"}


def outcome_cell(outcome: str) -> str:
    """Skipped and missed runs are not errors, so only failures are red."""
    colour = _COLOURS.get(outcome, "yellow")
    return f"[{colour}]{outcome}[/{colour}]"
