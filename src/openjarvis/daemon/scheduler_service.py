"""Run ``jarvis scheduler start`` as a macOS login service (D-009).

launchd starts the scheduler at login and restarts it after a crash. A lock
file keeps a hand-started scheduler and the service from both running tasks.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Callable

from openjarvis.core.paths import get_config_dir
from openjarvis.daemon.service import generate_launchd_plist
from openjarvis.security.file_utils import secure_mkdir

logger = logging.getLogger(__name__)

SCHEDULER_LABEL = "com.openjarvis.scheduler"
# launchctl normally answers at once; never let install/status hang on it.
_LAUNCHCTL_TIMEOUT_S = 30
_BOOTSTRAP_ATTEMPTS = 5

Runner = Callable[..., Any]


@dataclass(frozen=True)
class SchedulerServicePaths:
    plist: Path
    log_dir: Path
    lock: Path

    @classmethod
    def default(cls) -> SchedulerServicePaths:
        home = get_config_dir()
        return cls(
            plist=Path.home() / "Library" / "LaunchAgents" / f"{SCHEDULER_LABEL}.plist",
            log_dir=home / "logs",
            lock=home / "scheduler.lock",
        )

    @property
    def stdout_log(self) -> Path:
        return self.log_dir / "scheduler.out.log"

    @property
    def stderr_log(self) -> Path:
        return self.log_dir / "scheduler.err.log"


class SchedulerAlreadyRunning(RuntimeError):
    """Another process holds the scheduler lock."""


def _try_lock(path: Path) -> IO[str] | None:
    import fcntl  # POSIX-only; imported here so the CLI still loads on Windows

    secure_mkdir(path.parent)
    # Append mode so a refused attempt does not wipe the holder's pid.
    handle = open(path, "a", encoding="utf-8")  # noqa: SIM115
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def acquire_lock(path: Path) -> IO[str]:
    """Take the single-scheduler lock; keep the returned handle open to hold it.

    The OS drops the lock when the process exits, so a crash never leaves a
    stale lock behind. Raises ``SchedulerAlreadyRunning`` if it is held.
    """
    handle = _try_lock(path)
    if handle is None:
        raise SchedulerAlreadyRunning(str(path))
    handle.truncate(0)
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def is_lock_held(path: Path) -> bool:
    """Whether some process (including this one) holds the scheduler lock."""
    if not path.exists():
        return False
    probe = _try_lock(path)
    if probe is None:
        return True
    probe.close()
    return False


def program_args() -> list[str]:
    """Absolute command line launchd should run (it has no shell PATH)."""
    argv0 = Path(sys.argv[0])
    # absolute(), not resolve(): keep the venv's entry-point path, whose
    # shebang selects the right interpreter.
    if argv0.name == "jarvis":
        return [str(argv0.absolute()), "scheduler", "start"]
    found = shutil.which("jarvis")
    if found:
        return [os.path.abspath(found), "scheduler", "start"]
    return [sys.executable, "-m", "openjarvis.cli", "scheduler", "start"]


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(
    paths: SchedulerServicePaths,
    *,
    run: Runner = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Write the LaunchAgent plist and (re)load it; return the plist path.

    Raises ``subprocess.CalledProcessError`` if launchd refuses the service.
    """
    secure_mkdir(paths.log_dir)
    generate_launchd_plist(
        paths.plist,
        label=SCHEDULER_LABEL,
        program_args=program_args(),
        stdout_path=paths.stdout_log,
        stderr_path=paths.stderr_log,
        restart="on_crash",
        min_restart_interval_s=30,
    )
    # Unload any previous copy so the new plist takes effect.
    run(
        ["launchctl", "bootout", f"{_domain()}/{SCHEDULER_LABEL}"],
        check=False,
        capture_output=True,
        timeout=_LAUNCHCTL_TIMEOUT_S,
    )
    # bootout returns before launchd has released the old job, and bootstrap
    # fails (exit 5) until it has, which would leave no scheduler running.
    for attempt in range(_BOOTSTRAP_ATTEMPTS):
        try:
            run(
                ["launchctl", "bootstrap", _domain(), str(paths.plist)],
                check=True,
                capture_output=True,
                timeout=_LAUNCHCTL_TIMEOUT_S,
            )
            break
        except subprocess.CalledProcessError:
            if attempt == _BOOTSTRAP_ATTEMPTS - 1:
                raise
            sleep(1.0)
    logger.info("Installed scheduler service %s", paths.plist)
    return paths.plist


def uninstall(paths: SchedulerServicePaths, *, run: Runner = subprocess.run) -> bool:
    """Stop the service and remove its plist; ``False`` if it was not installed."""
    run(
        ["launchctl", "bootout", f"{_domain()}/{SCHEDULER_LABEL}"],
        check=False,
        capture_output=True,
        timeout=_LAUNCHCTL_TIMEOUT_S,
    )
    if not paths.plist.exists():
        return False
    paths.plist.unlink()
    logger.info("Removed scheduler service %s", paths.plist)
    return True


def status(paths: SchedulerServicePaths, *, run: Runner = subprocess.run) -> dict:
    """``{installed, loaded, running}``: plist present, known to launchd, lock held."""
    try:
        loaded = (
            run(
                ["launchctl", "print", f"{_domain()}/{SCHEDULER_LABEL}"],
                check=False,
                capture_output=True,
                timeout=_LAUNCHCTL_TIMEOUT_S,
            ).returncode
            == 0
        )
    except (OSError, subprocess.TimeoutExpired):
        loaded = False
    return {
        "installed": paths.plist.is_file(),
        "loaded": loaded,
        "running": is_lock_held(paths.lock),
    }


__all__ = [
    "SCHEDULER_LABEL",
    "SchedulerAlreadyRunning",
    "SchedulerServicePaths",
    "acquire_lock",
    "install",
    "is_lock_held",
    "program_args",
    "status",
    "uninstall",
]
