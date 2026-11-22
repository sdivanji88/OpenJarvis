"""``jarvis scheduler`` -- task scheduling commands."""

from __future__ import annotations

from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from openjarvis.cli.scheduler_service_cmd import scheduler_start, scheduler_status


def _get_store() -> "SchedulerStore":  # noqa: F821
    """Build a SchedulerStore from user config."""
    from openjarvis.scheduler.store import open_default_store

    return open_default_store()


def _get_scheduler(store: "SchedulerStore") -> "TaskScheduler":  # noqa: F821
    """Build a TaskScheduler from a store."""
    from openjarvis.scheduler.scheduler import TaskScheduler

    return TaskScheduler(store)


@click.group()
def scheduler() -> None:
    """Manage scheduled tasks."""


@scheduler.command("create")
@click.argument("prompt")
@click.option(
    "--type",
    "schedule_type",
    required=True,
    type=click.Choice(["cron", "interval", "once"]),
    help="Schedule type.",
)
@click.option(
    "--value",
    "schedule_value",
    required=True,
    help="Schedule value (cron expr, seconds, or ISO datetime).",
)
@click.option("--agent", default="simple", help="Agent to use for execution.")
@click.option("--tools", default="", help="Comma-separated tool names.")
def scheduler_create(
    prompt: str,
    schedule_type: str,
    schedule_value: str,
    agent: str,
    tools: str,
) -> None:
    """Create a new scheduled task."""
    console = Console()
    store = _get_store()
    try:
        sched = _get_scheduler(store)
        task = sched.create_task(
            prompt=prompt,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            agent=agent,
            tools=tools,
        )
        console.print(f"[green]Created task {task.id}[/green]")
        console.print(f"  Type: {task.schedule_type}")
        console.print(f"  Value: {task.schedule_value}")
        console.print(f"  Next run: {task.next_run or 'N/A'}")
        console.print(f"  Agent: {task.agent}")
        if task.tools:
            console.print(f"  Tools: {task.tools}")
    finally:
        store.close()


@scheduler.command("list")
@click.option(
    "--status",
    default=None,
    type=click.Choice(["active", "paused", "completed", "cancelled"]),
    help="Filter by status.",
)
def scheduler_list(status: Optional[str]) -> None:
    """List scheduled tasks."""
    console = Console()
    store = _get_store()
    try:
        sched = _get_scheduler(store)
        tasks = sched.list_tasks(status=status)

        if not tasks:
            console.print("[dim]No scheduled tasks found.[/dim]")
            return

        table = Table(title="Scheduled Tasks")
        table.add_column("ID", style="cyan")
        table.add_column("Prompt", max_width=40)
        table.add_column("Type", style="blue")
        table.add_column("Status", style="green")
        table.add_column("Next Run")
        table.add_column("Agent")

        for t in tasks:
            prompt_short = t.prompt[:37] + "..." if len(t.prompt) > 40 else t.prompt
            status_style = {
                "active": "green",
                "paused": "yellow",
                "completed": "dim",
                "cancelled": "red",
            }.get(t.status, "white")
            table.add_row(
                t.id,
                prompt_short,
                t.schedule_type,
                f"[{status_style}]{t.status}[/{status_style}]",
                t.next_run or "N/A",
                t.agent,
            )
        console.print(table)
    finally:
        store.close()


@scheduler.command("pause")
@click.argument("task_id")
def scheduler_pause(task_id: str) -> None:
    """Pause a scheduled task."""
    console = Console()
    store = _get_store()
    try:
        sched = _get_scheduler(store)
        sched.pause_task(task_id)
        console.print(f"[yellow]Task {task_id} paused[/yellow]")
    except KeyError:
        console.print(f"[red]Task not found: {task_id}[/red]")
    finally:
        store.close()


@scheduler.command("resume")
@click.argument("task_id")
def scheduler_resume(task_id: str) -> None:
    """Resume a paused task."""
    console = Console()
    store = _get_store()
    try:
        sched = _get_scheduler(store)
        sched.resume_task(task_id)
        console.print(f"[green]Task {task_id} resumed[/green]")
    except KeyError:
        console.print(f"[red]Task not found: {task_id}[/red]")
    finally:
        store.close()


@scheduler.command("cancel")
@click.argument("task_id")
def scheduler_cancel(task_id: str) -> None:
    """Cancel a scheduled task."""
    console = Console()
    store = _get_store()
    try:
        sched = _get_scheduler(store)
        sched.cancel_task(task_id)
        console.print(f"[red]Task {task_id} cancelled[/red]")
    except KeyError:
        console.print(f"[red]Task not found: {task_id}[/red]")
    finally:
        store.close()


@scheduler.command("logs")
@click.argument("task_id")
@click.option("-n", "--limit", default=10, type=int, help="Number of logs to show.")
def scheduler_logs(task_id: str, limit: int) -> None:
    """Show run logs for a scheduled task."""
    from openjarvis.cli._run_outcome import outcome_cell

    console = Console()
    store = _get_store()
    try:
        logs = store.get_run_logs(task_id, limit=limit)
        if not logs:
            console.print(f"[dim]No run logs for task {task_id}[/dim]")
            return

        table = Table(title=f"Run Logs for {task_id}")
        table.add_column("ID", justify="right")
        table.add_column("Started")
        table.add_column("Finished")
        table.add_column("Outcome")
        table.add_column("Result", max_width=40)
        table.add_column("Error", max_width=30)

        for log in logs:
            result_text = log["result"]
            result_short = (
                (result_text[:37] + "...") if len(result_text) > 40 else result_text
            )
            table.add_row(
                str(log["id"]),
                log["started_at"],
                log.get("finished_at") or "N/A",
                outcome_cell(log["outcome"]),
                result_short,
                log.get("error", ""),
            )
        console.print(table)
    finally:
        store.close()


@scheduler.command("run-task")
@click.argument("agent_name")
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Print what would run without executing.",
)
def scheduler_run_task(agent_name: str, dry_run: bool) -> None:
    """Immediately execute the active task for AGENT_NAME.

    Finds the first active scheduled task whose agent matches AGENT_NAME
    and runs it right now, for manual testing. It bypasses the scheduler
    allowlists; use 'jarvis scheduler start' for unattended runs.
    """
    console = Console()
    store = _get_store()
    try:
        sched = _get_scheduler(store)
        tasks = sched.list_tasks(status="active")
        match = next((t for t in tasks if t.agent == agent_name), None)

        if match is None:
            console.print(
                f"[yellow]No active task found for agent '{agent_name}'. "
                "Register it first with 'jarvis scheduler create'.[/yellow]"
            )
            return

        if dry_run:
            console.print("[dim]Dry run — would execute:[/dim]")
            console.print(f"  Task : {match.id}")
            console.print(f"  Agent: {match.agent}")
            console.print(f"  Prompt: {match.prompt[:80]}")
            return

        console.print(f"Running task [cyan]{match.id}[/cyan] (agent: {match.agent})…")

        from openjarvis.core.config import load_config
        from openjarvis.scheduler.scheduler import RunOutcome, TaskScheduler
        from openjarvis.system import SystemBuilder

        system = SystemBuilder(load_config()).build()
        record = TaskScheduler(store, system, bus=system.bus).run_now(match.id)
        if record.outcome is RunOutcome.FAILED:
            console.print(f"[red]Task failed: {record.error}[/red]")
            raise SystemExit(1)

        console.print("[green]Done.[/green]")
        if record.result:
            console.print(record.result)
    except Exception as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise SystemExit(1)
    finally:
        store.close()


scheduler.add_command(scheduler_start)
scheduler.add_command(scheduler_status)
