# Task Scheduler

The task scheduler lets you run agent queries automatically on a schedule -- once at a future time, on a recurring interval, or via a cron expression. Scheduled tasks are persisted in SQLite so they survive process restarts, and execution is handled by a background daemon thread that polls for due tasks every 60 seconds.

!!! note "Who runs scheduled tasks"
    `jarvis scheduler start` is the only process that runs scheduled tasks. `jarvis serve` does **not** run them. Install the scheduler as a macOS login service with `jarvis scheduler start --install` so tasks keep running after you close the terminal or restart.

---

## Schedule Types

| `schedule_type` | `schedule_value` format            | Example                     | Meaning                             |
|-----------------|------------------------------------|-----------------------------|-------------------------------------|
| `once`          | ISO 8601 UTC datetime              | `"2026-03-01T09:00:00Z"`    | Run once at that timestamp          |
| `interval`      | Seconds as a string                | `"3600"`                    | Run every hour, starting immediately |
| `cron`          | Standard 5-field cron expression   | `"0 9 * * 1-5"`             | 09:00 UTC, Monday–Friday            |

!!! tip "Cron support"
    Full cron expression support requires `croniter` (`uv pip install croniter`). Without it, the scheduler uses a minimal built-in parser that handles simple `minute hour * * *` patterns only.

---

## CLI Commands

The `jarvis scheduler` subcommand group manages tasks and the daemon from the terminal.

### Start the daemon

```bash
jarvis scheduler start             # foreground, until Ctrl+C (--verbose for DEBUG logs)
jarvis scheduler start --install   # macOS: install and load a launchd login service
jarvis scheduler start --uninstall # remove the login service
jarvis scheduler status            # installed / loaded / running
```

The daemon builds a fresh Jarvis system for every run, so Ollama being down at login or a config edit needs no restart, except for `scheduler.allowed_agents` / `scheduler.allowed_tools`, which are read at startup. Only allowlisted agents and tools run (see [Unattended runs](#unattended-runs)). A lock file (`~/.openjarvis/scheduler.lock`) keeps a second scheduler from running tasks: it prints `A scheduler is already running …; nothing to do.` and exits 0, so a hand-started one and the service never both run tasks.

`--install` writes `~/Library/LaunchAgents/com.openjarvis.scheduler.plist` (starts at login and restarts after a crash, but not after a clean stop or when another scheduler is already running) and logs to `~/.openjarvis/logs/scheduler.out.log` and `scheduler.err.log`. The plist never contains secrets: the service loads keys from the owner-only `~/.openjarvis/credentials.toml`, and `--install` offers to copy `CARTESIA_API_KEY` there from your shell. It also offers to copy your digest persona into `~/.openjarvis/prompts/personas/`, because launchd does not run from your checkout. On Linux, run `jarvis scheduler start` under systemd or another supervisor (see [Deployment](../deployment/systemd.md)).

`jarvis scheduler run-task AGENT` runs a task immediately for testing and records it in `jarvis scheduler logs` like a scheduled run, without moving its schedule. It bypasses both allowlists (`allowed_agents` and `allowed_tools`) and the misfire window, so keep it a manual operator command; it exits 1 if the run fails.

### Create a task

```bash
# Run once at a specific time
jarvis scheduler create "Generate the weekly summary report" \
  --type once \
  --value "2026-03-01T09:00:00Z"

# Run every hour
jarvis scheduler create "Check for new emails and summarize" \
  --type interval \
  --value "3600" \
  --agent orchestrator \
  --tools retrieval,think

# Run on a cron schedule
jarvis scheduler create "Summarize overnight logs" \
  --type cron \
  --value "0 8 * * 1-5"
```

### List tasks

```bash
# All tasks
jarvis scheduler list

# Active tasks only
jarvis scheduler list --status active

# Paused tasks
jarvis scheduler list --status paused
```

Example output:

```
ID               AGENT     TYPE       VALUE          STATUS   NEXT RUN
a3f9b12c4d8e    simple    cron       0 8 * * 1-5    active   2026-02-26T08:00:00+00:00
b7c2e56f1a3d    orchestr  interval   3600           active   2026-02-25T14:05:00+00:00
```

### Pause and resume tasks

```bash
# Pause a running task
jarvis scheduler pause a3f9b12c4d8e

# Resume -- next_run is recomputed from the current time
jarvis scheduler resume a3f9b12c4d8e
```

### Cancel a task

```bash
# Permanently cancel (status -> "cancelled", next_run cleared)
jarvis scheduler cancel a3f9b12c4d8e
```

### View run logs

```bash
# Last 10 executions for a task
jarvis scheduler logs a3f9b12c4d8e
```

Example output:

```
 ID  Started               Finished              Outcome  Result                      Error
  3  2026-02-26T08:00:00Z  2026-02-26T08:00:00Z  missed                              240 min late (grace 180)
  2  2026-02-25T08:00:01Z  2026-02-25T08:00:04Z  success  Overnight logs contain 3…
  1  2026-02-24T08:00:00Z  2026-02-24T08:00:05Z  success  Logs are clean.
```

---

## Unattended runs

Scheduled tasks run with nobody watching, so the daemon is deny-by-default. List the agents it may run and the tools those agents may use:

```toml title="~/.openjarvis/config.toml"
[scheduler]
allowed_agents = ["morning_digest"]
allowed_tools = ["digest_collect", "text_to_speech"]
```

- A task whose agent is not in `allowed_agents` is skipped and logged.
- Every tool call in the daemon process goes through OpenJarvis's tool executor, which refuses tools outside `allowed_tools`, including tools an agent adds for itself. Agents cannot create scheduled tasks from inside the daemon.
- `allowed_tools` matches the tool name the agent exposes to the model, so a tool an agent offers under a different name is checked under that name.
- Some agents call tools outside the executor, so `allowed_tools` does not cover them: `claude_code` and `opencode` (external CLIs with their own tools) and the hybrid agents in `agents/hybrid` (for example, their Tavily search context calls the web search tool directly). Only `allowed_agents` guards them, so list them only if you accept that.
- A one-shot (`once`) task whose agent is not allowed is skipped and paused, not completed. Add the agent to `allowed_agents`, restart the service, then `jarvis scheduler resume <task-id>` to run it.
- Both lists are read at startup. After changing them, restart the service: `launchctl kickstart -k gui/$UID/com.openjarvis.scheduler`.

Each slot runs at most once: the task's next run time is advanced *before* it executes, so a crash or failure is not retried in the same slot. Every run is recorded in `jarvis scheduler logs` (with the reply text) and as one audit line in the service log, with one of these outcomes:

| Outcome   | Meaning                                                      |
|-----------|--------------------------------------------------------------|
| `success` | The agent ran and replied                                    |
| `failed`  | The agent raised an error (recorded in the run log)          |
| `skipped` | The agent is not in `scheduler.allowed_agents`               |
| `missed`  | The run was later than the task's `misfire_grace_minutes`    |

`jarvis scheduler logs` shows the outcome in its Outcome column; the Error column only explains it in words. Runs recorded before the outcome was stored show `success` or `failed`, derived from the old success flag.

**Interval spacing.** Interval tasks are spaced start-to-start: the next run time is computed when a run is claimed, not when it finishes. A run that takes longer than its interval is due again at the next poll after it ends. Each slot still runs at most once.

**Late runs.** Nothing runs while the machine sleeps. A task may set `metadata.misfire_grace_minutes`; a run later than that is skipped as `missed` and the task moves to its next slot. Tasks without the setting catch up as soon as the daemon sees them. `jarvis digest --schedule` sets 180 minutes for the morning digest.

---

## Python API

```python title="scheduler_example.py"
from openjarvis.scheduler.store import SchedulerStore
from openjarvis.scheduler.scheduler import TaskScheduler

# Set up storage
store = SchedulerStore(db_path="~/.openjarvis/scheduler.db")  # (1)!

# Wire in a JarvisSystem for task execution
from openjarvis import Jarvis
jarvis = Jarvis()

scheduler = TaskScheduler(
    store=store,
    system=jarvis,         # (2)!
    poll_interval=60,      # (3)!
)

# Create tasks
daily_summary = scheduler.create_task(
    prompt="Summarize the latest news headlines",
    schedule_type="cron",
    schedule_value="0 8 * * *",
    agent="simple",
)
print(f"Created task {daily_summary.id}, next run: {daily_summary.next_run}")

# List active tasks
for task in scheduler.list_tasks(status="active"):
    print(f"  {task.id}: {task.prompt} @ {task.next_run}")

# Manage task state
scheduler.pause_task(daily_summary.id)
scheduler.resume_task(daily_summary.id)   # next_run recomputed from now
scheduler.cancel_task(daily_summary.id)  # permanent

# Start the background thread
scheduler.start()   # (4)!

# ... application runs ...

scheduler.stop()
jarvis.close()
```

1. SQLite database storing all task state and run logs.
2. The scheduler calls `system.ask(task.prompt, agent=task.agent, tools=...)` when a task is due. Pass `system=None` for a dry-run mode that logs what it would execute without calling the agent.
3. Seconds between polling cycles. Lower values increase responsiveness at the cost of more SQLite reads.
4. Starts a daemon thread named `"jarvis-scheduler"`. Daemon threads exit automatically when the main process exits.

---

## ScheduledTask Fields

Every task is represented as a `ScheduledTask` dataclass.

| Field            | Type              | Default       | Description                                       |
|------------------|-------------------|---------------|---------------------------------------------------|
| `id`             | `str`             | auto (16 hex) | Unique task identifier                            |
| `prompt`         | `str`             | --            | Query sent to the agent on execution              |
| `schedule_type`  | `str`             | --            | `"cron"`, `"interval"`, or `"once"`              |
| `schedule_value` | `str`             | --            | Cron expression, interval seconds, or ISO datetime|
| `context_mode`   | `str`             | `"isolated"`  | Execution context mode                            |
| `status`         | `str`             | `"active"`    | `"active"`, `"paused"`, `"completed"`, `"cancelled"` |
| `next_run`       | `str` or `None`   | computed      | ISO 8601 UTC datetime of the next execution       |
| `last_run`       | `str` or `None`   | `None`        | ISO 8601 UTC datetime of the last execution       |
| `agent`          | `str`             | `"simple"`    | Agent registry key to use for execution           |
| `tools`          | `str`             | `""`          | Comma-separated tool names for the agent          |
| `metadata`       | `dict`            | `{}`          | Arbitrary metadata for the task                   |

---

## Using Scheduler Tools with Agents

The five scheduler MCP tools (`schedule_task`, `list_scheduled_tasks`, `pause_scheduled_task`, `resume_scheduled_task`, `cancel_scheduled_task`) can be passed to any `ToolUsingAgent`, allowing an agent to schedule follow-up tasks autonomously.

```bash
# Let the orchestrator schedule its own follow-up
jarvis ask --agent orchestrator \
  --tools schedule_task,list_scheduled_tasks \
  "Research transformer architectures and schedule a daily summary at 8am"
```

```python
from openjarvis import Jarvis

j = Jarvis()
response = j.ask(
    "Schedule a weekly digest of research papers every Monday at 9am",
    agent="orchestrator",
    tools=["schedule_task"],
)
print(response)
```

See [Scheduler Tools](tools.md#scheduler-tools) for full parameter reference.

---

## Configuration

Scheduler settings live in the `[scheduler]` section of `~/.openjarvis/config.toml`.

```toml title="~/.openjarvis/config.toml"
[scheduler]
enabled = false
db_path = "~/.openjarvis/scheduler.db"
poll_interval = 60
default_agent = "simple"
allowed_agents = ["morning_digest"]
allowed_tools = ["digest_collect", "text_to_speech"]
```

| Key              | Type   | Default                          | Description                                |
|------------------|--------|----------------------------------|--------------------------------------------|
| `enabled`        | `bool` | `false`                          | Start the scheduler daemon automatically   |
| `db_path`        | `str`  | `~/.openjarvis/scheduler.db`     | SQLite database path                       |
| `poll_interval`  | `int`  | `60`                             | Seconds between polling cycles             |
| `default_agent`  | `str`  | `"simple"`                       | Default agent for tasks that omit `agent`  |
| `allowed_agents` | `list` | `[]` (nothing runs)              | Agents `jarvis scheduler start` may run    |
| `allowed_tools`  | `list` | `[]` (no tools)                  | Tools those agents may call                |

---

## See Also

- [Scheduler Tools reference](tools.md#scheduler-tools) -- MCP tool parameter details
- [Architecture: Agentic Logic](../architecture/agents.md) -- how the scheduler integrates with agents
- [Deployment: systemd](../deployment/systemd.md) -- running the scheduler as a system service
