"""``jarvis scheduler start|status`` — the process that runs scheduled tasks.

This daemon is the only runner of scheduled tasks (D-008); ``jarvis serve``
does not run them. It runs only allowlisted agents and tools (D-011).
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import threading
from typing import Any

import click

from openjarvis.daemon import scheduler_service as service

logger = logging.getLogger(__name__)

TOOL_BLOCKED_REASON = "not in scheduler.allowed_tools (unattended runs)"

# Module-level seams so tests never touch launchd, the real lock, or block.
_launchctl_run = subprocess.run


def _paths() -> service.SchedulerServicePaths:
    return service.SchedulerServicePaths.default()


def _open_store() -> Any:
    from openjarvis.scheduler.store import open_default_store

    return open_default_store()


def _wait_for_shutdown() -> None:
    """Block until SIGINT or SIGTERM (launchd stops services with SIGTERM)."""
    stop = threading.Event()

    def _handle(signum: int, frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    while not stop.wait(timeout=1.0):
        pass


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    package = logging.getLogger("openjarvis")
    if not root.handlers and not package.handlers:
        logging.basicConfig(
            level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
        )
    package.setLevel(level)
    for handler in (*root.handlers, *package.handlers):
        handler.setLevel(level)


def _warn_if_nothing_allowed(policy: Any) -> None:
    if not policy.allowed_agents:
        click.echo(
            "Warning: scheduler.allowed_agents is empty, so no task will run. "
            'Add e.g. allowed_agents = ["morning_digest"] under [scheduler].',
            err=True,
        )
    if not policy.allowed_tools:
        click.echo(
            "Warning: scheduler.allowed_tools is empty, so agents get no tools "
            '(the digest needs ["digest_collect", "text_to_speech"]).',
            err=True,
        )


def _run_foreground(poll_interval: int, verbose: bool) -> None:
    from openjarvis.agents.digest_playback import DigestAutoplay
    from openjarvis.core.config import load_config
    from openjarvis.core.events import EventBus
    from openjarvis.scheduler.policy import RunPolicy
    from openjarvis.scheduler.runtime import OnDemandSystem
    from openjarvis.scheduler.scheduler import TaskScheduler
    from openjarvis.security.tool_allowlist import restrict_process_tools

    _configure_logging(verbose)
    paths = _paths()
    try:
        lock = service.acquire_lock(paths.lock)
    except service.SchedulerAlreadyRunning:
        # The goal (one scheduler running) already holds, so exit 0: launchd
        # restarts the service only after a failed exit.
        click.echo(
            f"A scheduler is already running (lock: {paths.lock}); nothing to do."
        )
        return

    policy = RunPolicy.from_config(load_config().scheduler)
    # Set once, before any task can run: every tool call in this process now
    # goes through the allowlist (D-011).
    restrict_process_tools(policy.allowed_tools, reason=TOOL_BLOCKED_REASON)
    store = _open_store()
    # A private bus: per-run systems get their own, so nothing else listens here.
    bus = EventBus()
    DigestAutoplay().attach(bus)
    sched = TaskScheduler(
        store,
        OnDemandSystem(),
        bus=bus,
        policy=policy,
        poll_interval=poll_interval,
    )
    logger.info(
        "Scheduler allowlists: agents=%s tools=%s",
        sorted(policy.allowed_agents),
        sorted(policy.allowed_tools),
    )
    if not policy.allowed_agents:
        logger.warning("scheduler.allowed_agents is empty; no task will run")
    sched.start()
    click.echo(f"Scheduler running (poll every {poll_interval}s). Ctrl+C to stop.")
    try:
        _wait_for_shutdown()
    finally:
        sched.stop()
        store.close()
        lock.close()
        click.echo("Scheduler stopped.")


def _offer_cartesia_key() -> None:
    """Copy the shell's Cartesia key into credentials.toml (launchd has no shell)."""
    from openjarvis.core.credentials import load_credentials, save_credential

    value = os.environ.get("CARTESIA_API_KEY", "").strip()
    if not value:
        return
    if any("CARTESIA_API_KEY" in kvs for kvs in load_credentials().values()):
        return
    if click.confirm(
        "Copy CARTESIA_API_KEY from this shell into the owner-only "
        "credentials.toml so the service can speak the digest?",
        default=False,
    ):
        save_credential("text_to_speech", "CARTESIA_API_KEY", value)
        click.echo("Saved CARTESIA_API_KEY to credentials.toml.")


def _offer_persona_copy(persona: str) -> None:
    """launchd runs with cwd=/, so a checkout-relative persona would not load."""
    from openjarvis.agents.morning_digest import checkout_persona_dir, user_persona_dir

    # digest.persona becomes a path component on both sides of the copy.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", persona or ""):
        return
    source = checkout_persona_dir() / f"{persona}.md"
    dest = user_persona_dir() / f"{persona}.md"
    if not source.is_file() or dest.exists():
        return
    if click.confirm(f"Copy persona '{persona}' to {dest}?", default=True):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        click.echo(f"Copied persona to {dest}")


def _install() -> None:
    from openjarvis.core.config import load_config
    from openjarvis.scheduler.policy import RunPolicy

    if platform.system() != "Darwin":
        click.echo(
            "--install supports macOS launchd only. Elsewhere, run "
            "'jarvis scheduler start' under your service manager "
            "(see docs/user-guide/scheduler.md).",
            err=True,
        )
        raise SystemExit(1)
    config = load_config()
    if config.digest.tts_backend == "cartesia":
        _offer_cartesia_key()
    _offer_persona_copy(config.digest.persona)
    _warn_if_nothing_allowed(RunPolicy.from_config(config.scheduler))
    paths = _paths()
    try:
        plist = service.install(paths, run=_launchctl_run)
    except subprocess.CalledProcessError as exc:
        click.echo(f"launchctl refused the service (exit {exc.returncode}).", err=True)
        raise SystemExit(1)
    except subprocess.TimeoutExpired:
        click.echo("launchctl did not respond; service not loaded.", err=True)
        raise SystemExit(1)
    click.echo(f"Installed {plist}")
    click.echo(f"Logs: {paths.stdout_log} and {paths.stderr_log}")


def _uninstall() -> None:
    paths = _paths()
    if service.uninstall(paths, run=_launchctl_run):
        click.echo(f"Removed {paths.plist}")
    else:
        click.echo("Scheduler service was not installed.")


@click.command("start")
@click.option("--poll-interval", default=60, type=int, help="Seconds between polls.")
@click.option(
    "--install", is_flag=True, help="Install as a macOS login service (launchd)."
)
@click.option("--uninstall", is_flag=True, help="Remove the login service.")
@click.option("--verbose", is_flag=True, help="Log at DEBUG level.")
def scheduler_start(
    poll_interval: int, install: bool, uninstall: bool, verbose: bool
) -> None:
    """Run scheduled tasks (foreground), or install/remove the login service.

    Only agents in scheduler.allowed_agents run, with only the tools in
    scheduler.allowed_tools. Restart the service after changing either list.
    """
    if install and uninstall:
        raise click.UsageError("Use only one of --install and --uninstall.")
    if install:
        _install()
    elif uninstall:
        _uninstall()
    else:
        _run_foreground(poll_interval, verbose)


@click.command("status")
def scheduler_status() -> None:
    """Show whether the scheduler service is installed, loaded, and running."""
    paths = _paths()
    state = service.status(paths, run=_launchctl_run)
    for key in ("installed", "loaded", "running"):
        click.echo(f"{key}: {'yes' if state[key] else 'no'}")
    click.echo(f"plist: {paths.plist}")
    click.echo(f"logs: {paths.stdout_log}, {paths.stderr_log}")
    click.echo(f"lock: {paths.lock}")


__all__ = ["scheduler_start", "scheduler_status"]
