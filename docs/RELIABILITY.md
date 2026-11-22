# Reliability — OpenJarvis

> Performance baselines, scale, observability, failure modes, and operational characteristics.

## Performance targets

No formal SLOs are defined. The following observed figures serve as baselines; regressions against them should be investigated.

- **Apple FM time-to-first-chunk:** ~450 ms on M1 Pro (`docs/architecture/engine.md`)
- **Jetson Orin decode:** 15–25 tok/s (`docs/development/roadmap.md`)
- **Installer:** completes in ~3 minutes (README)
- **Server rate limit (default):** 60 req/min, burst 10 (`core/config.py`)
- **Sandbox (default):** max 5 concurrent, 300 s timeout (`core/config.py`)

Specific targets:

- **Latency (p50 / p95 / p99):** {{TODO}}
- **Throughput:** {{TODO}}
- **Resource budget (CPU / memory / energy):** {{TODO}}
- **Startup time (`jarvis --help`, `jarvis serve`):** {{TODO}}

## Scale targets

Single user, single local device, local SQLite data. The Render deployment is a demo only (free plan, ephemeral filesystem).

- **Concurrent users:** 1 (local)
- **Requests per second sustained:** bounded by local inference; server rate limit 60 req/min by default
- **Data volume:** {{TODO: expected size of telemetry/traces/connector data per user}}
- **Failure isolation boundary:** the local process / device

## Observability

### Logging

Modules use stdlib `logging.getLogger(__name__)`; CLI output goes through Rich. Logs are **not** JSON-structured today.

{{TODO: decide whether to adopt structured (JSON) logging at service boundaries (server routes, channel handlers, connectors).}}

### Metrics

Every inference call records latency, TTFT, tokens, energy, and power to SQLite via `src/openjarvis/telemetry/` (energy monitors for NVIDIA, AMD, Apple, RAPL). Product analytics via PostHog (see `docs/telemetry.md`).

### Tracing

Agent/tool traces stored locally via `src/openjarvis/traces/` and consumed by the learning loop. Components emit events through `core/events.py` (`EventBus`).

### Dashboards & alerts

{{TODO: links to dashboards (web UI telemetry pages?) — no paging alerts expected for a local-first app.}}

## Failure modes

{{TODO: catalog of known failure modes. Likely categories:
- Inference engine not running / model not pulled (Ollama down)
- Cloud API timeout or missing key
- Connector OAuth token expired
- Energy monitor unavailable on platform
- SQLite locked / corrupted under OPENJARVIS_HOME
- Rust extension not built
}}

### Scheduler daemon

- **Restart:** the launchd service (`com.openjarvis.scheduler`) starts at login and restarts after a crash (non-zero exit), throttled to once per 30 s. A clean exit — including finding another scheduler already holding the lock — is not restarted. Allowlist changes need `launchctl kickstart -k gui/$UID/com.openjarvis.scheduler`.
- **At-most-once:** a task's `next_run` is advanced (compare-and-set) before it executes, so a crash, failure, or a second scheduler never repeats a slot; the cost is that a run killed mid-flight is not retried. A lock file (`~/.openjarvis/scheduler.lock`) refuses a second instance.
- **Late runs:** tasks with `metadata.misfire_grace_minutes` are logged as `missed` beyond the window (digest: 180 min); others catch up on wake.
- **Engine down:** each run builds a fresh system, so a run while Ollama is down is logged `failed` and the next slot proceeds normally.
- **Logs:** `~/.openjarvis/logs/scheduler.{out,err}.log` are not rotated and grow without bound; truncate them manually if needed. Audit lines carry task id, agent, outcome, tools, and duration — never prompt, result, or error text.

## Backpressure & degradation

Server rate limiting (60 req/min, burst 10) and sandbox concurrency caps. {{TODO: document local→cloud fallback behavior and what happens when no engine is available.}}

## Disaster recovery

{{TODO: backup/restore of OPENJARVIS_HOME (databases, config, connector tokens).}}

## Deployment

PyPI (`uv build && uv publish` on `vX.Y.Z` tags; `.devN` autotags on `main`), Docker images (CPU / CUDA / ROCm / sandbox) in `deploy/docker/`, Render blueprint (`render.yaml`), Tauri desktop installers with auto-update (`desktop.yml`), `install.sh`/`install.ps1`, launchd/systemd/Windows service units, mkdocs site on GitHub Pages.

### Rollout strategy

Dev builds auto-tagged on every push to `main`; stable releases cut from `vX.Y.Z` tags. Desktop updater polls the `desktop-latest` channel. {{TODO: any staged rollout for desktop?}}

### Rollback

{{TODO: yank/pin a PyPI release; repoint desktop-latest channel.}}

## Capacity planning

{{TODO: leading indicators — e.g. telemetry DB growth, memory per loaded model.}}
