"""The system the scheduler daemon runs unattended tasks against."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from openjarvis.core.config import load_config
from openjarvis.core.credentials import inject_credentials

logger = logging.getLogger(__name__)


def _build_system() -> Any:
    from openjarvis.core.events import EventBus
    from openjarvis.system import SystemBuilder

    # No task scheduler inside the run: schedule-task tools then have nothing
    # to create tasks with, so an unattended agent cannot schedule more work.
    return SystemBuilder(load_config()).scheduler(False).event_bus(EventBus()).build()


class OnDemandSystem:
    """Fresh JarvisSystem per ``ask()``.

    Building per run means a daemon started at login (before Ollama is up)
    or left running across config edits still uses the current engine and
    settings. Credentials from ``credentials.toml`` are loaded into the
    environment before each build, because launchd services do not read shell
    profiles. Tool restriction is not done here: the daemon sets the
    process-wide allowlist (``security.tool_allowlist``) once at startup.
    """

    def __init__(
        self,
        *,
        credentials_path: Optional[Path] = None,
        build: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._credentials_path = credentials_path
        self._build = build or _build_system

    def ask(self, prompt: str, **kwargs: Any) -> Any:
        """Run *prompt* on a new system and return its raw result."""
        inject_credentials(self._credentials_path)
        load_config.cache_clear()
        system = self._build()
        try:
            return system.ask(prompt, **kwargs)
        finally:
            system.close()


__all__ = ["OnDemandSystem"]
