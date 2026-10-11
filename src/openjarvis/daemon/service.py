from __future__ import annotations

import plistlib
import sys
from pathlib import Path
from typing import Literal

SYSTEMD_TEMPLATE = """\
[Unit]
Description=OpenJarvis Gateway Daemon
After=network.target

[Service]
Type=simple
ExecStart={python} -m openjarvis.daemon.gateway
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""


def generate_systemd_service(output: Path | None = None) -> str:
    content = SYSTEMD_TEMPLATE.format(python=sys.executable)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    return content


def generate_launchd_plist(
    output: Path | None = None,
    *,
    label: str = "com.openjarvis.gateway",
    program_args: list[str] | None = None,
    stdout_path: Path | None = None,
    stderr_path: Path | None = None,
    restart: Literal["always", "on_crash"] = "always",
    min_restart_interval_s: int | None = None,
) -> str:
    """plistlib-built LaunchAgent that starts at load; never EnvironmentVariables.

    The plist is world-readable, so secrets must reach the service another way
    (``~/.openjarvis/credentials.toml``). Defaults describe the gateway daemon.

    *restart* ``"always"`` keeps the service running whenever it exits.
    ``"on_crash"`` has launchd respawn it only after a non-zero exit, so a
    clean stop (or a run that exits because another instance holds its lock)
    stays down. *min_restart_interval_s* is the shortest gap launchd leaves
    between starts (its ``ThrottleInterval``); ``None`` keeps launchd's default.
    """
    if restart == "always":
        keep_alive: bool | dict = True
    elif restart == "on_crash":
        keep_alive = {"SuccessfulExit": False}
    else:
        raise ValueError(f"restart must be 'always' or 'on_crash', not {restart!r}")
    plist: dict = {
        "Label": label,
        "ProgramArguments": program_args
        or [sys.executable, "-m", "openjarvis.daemon.gateway"],
        "RunAtLoad": True,
        "KeepAlive": keep_alive,
    }
    if stdout_path is not None:
        plist["StandardOutPath"] = str(stdout_path)
    if stderr_path is not None:
        plist["StandardErrorPath"] = str(stderr_path)
    if min_restart_interval_s is not None:
        plist["ThrottleInterval"] = min_restart_interval_s
    content = plistlib.dumps(plist).decode("utf-8")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
    return content
