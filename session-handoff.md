# Session Handoff — OpenJarvis

> Read this at the start of every session. Update it before ending every session.

**Last updated:** 2026-11-02T14:50:00Z

---

## Latest session (2026-11-02): F-030 verified

- **F-030 is `verified`.** All 8 criteria pass with evidence, and all hard gates exit 0 on the final tree; see `feature_list.json`. It is on branch `openshell-sandbox` in [PR #1](https://github.com/sdivanji88/OpenJarvis/pull/1).
- Added this session:
  - `sandbox/openshell_preflight.py`. Runs are refused when the machine is missing, rootless or stopped, the gateway isn't connected, or the image isn't in the cluster. Mounted host folders only warn (D-046).
  - Pre-flight runs again on every attempt, so fixing the problem is enough.
  - The same checks appear as rows in `jarvis doctor`.
  - Sandbox names carry the owner PID (`oj-<pid>-<agent>-<hex>`). At startup a process deletes only sandboxes whose owner is dead, so it no longer kills the scheduler's sandboxes.
  - The image build script removes older images.
  - The user guide is at `docs/user-guide/openshell-sandbox.md` and is in the mkdocs nav.
  - D-047: `uv.lock` patched for aiohttp, certifi, filelock and virtualenv advisories. Python 3.10 keeps filelock 4.1.0.
- **Machine state (D-046 migration):**
  - The gateway now runs on a dedicated rootful Podman machine `openshell` (4 CPU, 8 GiB, no host mounts). `podman-machine-default` is **stopped**; only one machine runs at a time on macOS. The old gateway on the default machine was destroyed.
  - `export DOCKER_HOST=unix:///var/folders/2h/6kqfgztx11j4bpk1x3m21wp00000gn/T/podman/openshell-api.sock` before `openshell` commands.
  - The user must start machines from their own terminal; one started from an agent shell dies with the command.
  - To restart a stopped gateway, run `podman --connection openshell-root start openshell-cluster-openshell` (about 2 min). Non-interactive `openshell gateway start` doesn't start it, and `--recreate` wipes the image.
  - Image: `openshell/sandbox-from:1793630675`. The gateway has no inference route, so sandboxed runs get 503 "cluster inference is not configured" until F-031.
- The real `~/.openjarvis/config.toml` is **unchanged** (runtime not openshell), so the 07:00 digest keeps working. Live checks used `OPENJARVIS_CONFIG=/tmp/oj-openshell/config.toml`.
- **Next:** F-031 (gateway key and pass-through model endpoint, D-043).

## Earlier session (2026-11-01, later): F-030 started test-first; F-029 verified

- **F-029 is `verified`** (developer sign-off on FINDINGS).
- **F-030 is `in_progress`** on branch `openshell-sandbox`, in [PR #1](https://github.com/sdivanji88/OpenJarvis/pull/1). The PR is on the fork with base `morning-digest`; change the base to `main` once `morning-digest` merges.
  - Done:
    - `sandbox/openshell_policy.py` (deny-all policy plus allowed hosts).
    - `sandbox/openshell_pool.py` (keyed, single-use, background refill).
    - `sandbox/openshell_cli.py` (create, SSH exec, delete, list, gateway check).
    - `sandbox/openshell_runner.py` (fails closed; `shared_runner()` per process).
    - `[sandbox.allowed_hosts]` and `[sandbox.pool_sizes]` config.
    - `agents/factory.py` `build_agent()` used at all 11 construction sites, with a guard test (D-044).
    - `SystemBuilder` hands the shared runner to `JarvisSystem`.
  - D-045: with `runtime = "openshell"`, runs fail closed until the in-sandbox entrypoint and F-031 land.
  - Also done:
    - The in-sandbox entrypoint (`sandbox/entrypoint.py`).
    - The slim image (`deploy/openshell/`), built by `scripts/build-openshell-image.sh`. The build stages a wheel and hash-checked Linux wheels on the host, so the image build needs no network apart from apt `iproute2`, which OpenShell's supervisor needs. The script prints the `[sandbox] image` tag.
    - End to end: `build_agent(SimpleAgent)` under `runtime = "openshell"` answered "pong" from inside a sandbox, through the gateway.
  - AC-002, AC-003, AC-004 and AC-005 are `pass` with evidence.
  - Left in F-030:
    - `jarvis doctor` checks (AC-007).
    - The refusal checks for a machine that isn't rootful and a missing image (AC-006).
    - Dedicated Podman machine guidance (D-042).
    - Pruning old `openshell/sandbox-from` images.
    - Evidence for AC-001 and AC-008.
    - The Definition of Done gates.
  - Gateway state:
    - The temporary provider `oj-dev-ollama` was deleted on 2026-11-02, and no providers remain. OpenShell has no command to clear the inference route, so it still names the deleted provider, and sandboxed model calls fail (`engine not reachable at https://inference.local`) until F-031 sets the route.
    - The current image is `openshell/sandbox-from:1793544465`.
- Full unit suite: 9222 passed. 3 failed in `tests/security/test_data_boundary_audit.py`; they fail the same way without this branch's changes.

## Earlier session (2026-11-01): OpenShell agent sandboxing — design agreed, spike F-029 run

- **Design agreed (D-029 to D-038), features F-029 to F-033 added.** Every agent run executes in a disposable OpenShell sandbox from a warm pool. Model calls go through the OpenShell inference gateway to OpenJarvis `/v1`, and the run fails closed when OpenShell is unavailable. Spec and plan are local only (gitignored): `docs/superpowers/specs/2026-11-01-openshell-sandbox-design.md`, `docs/superpowers/plans/2026-11-01-openshell-spike-f029.md`.
- **Spike F-029 is `verifying`.** Findings are in `docs/spikes/openshell/FINDINGS.md`.
  - Creating a sandbox takes ~2 s with a cached image. Deny-all is enforced from the first command. Live policy changes work but take 2–10 s.
  - Providers can't be attached after creation. Their credentials never enter the sandbox: the sandbox holds a placeholder that the proxy substitutes in headers and URL query strings.
  - The gateway forwards to `jarvis serve` through `host.openshell.internal`, and telemetry records the call.
- **Machine state:**
  - The Podman machine is now **rootful**, which the gateway requires. The gateway `openshell` is running in the Podman VM.
  - The 1.13 GB `base` image is cached in the cluster.
  - The gateway's inference route still names the deleted provider `oj-spike-jarvis`. Overwrite it with `openshell inference set` before relying on it.

- **Design revised after the spike (D-039 to D-043), agreed.** Follow-up checks showed that provider credentials are substituted on every allowed host (FINDINGS F1), and that the Podman VM mounts `/Users` (F4).
  - D-039: connectors run on the host, and sandboxes hold no credentials.
  - D-040: one pool keyed by policy and image, sized per agent.
  - D-041: a slim, dedicated OpenShell image.
  - D-042: a dedicated Podman machine with no host mounts.
  - D-043: a separate gateway key on a pass-through model endpoint.
  F-030, F-031 and F-032 were updated (F-032 is now the host-side connector endpoint).

### Next step — start here

F-030 is verified (see the latest session above). Start F-031: the gateway key and the pass-through model endpoint (D-043).

---

## What was accomplished (previous sessions)

- **F-025 (WhatsApp business updates in the morning digest): design agreed, not built.** This was a design-only session; decisions D-018 to D-026 are in `docs/DECISION_LOG.md`.
  - A new `whatsapp_desktop` connector will read the WhatsApp Mac app's local SQLite data read-only, for business chats only. Certified business names are included automatically, profile-only chats need approval through `jarvis whatsapp review`, and an exclude list overrides both.
  - The digest will get its own WHATSAPP section after Calendar. Processing is local only, and Cartesia gets only redacted lines.
  - F-026 (web UI review screen) is tracked as `todo`.
  - The database was inspected read-only (schemas and counts only).

- **F-021, F-022, F-024 are `verified`.** Every hard gate passed on the final tree, and the user confirmed hearing the scheduled 16:13 test digest.
- **F-024 (scheduled digest runs and plays at 07:00).** Design D-008 to D-013.
  - `jarvis scheduler start` is the single real runner. It builds a fresh system per run and loads credentials from `~/.openjarvis/credentials.toml`.
  - Each slot is claimed before it runs, and every run gets an outcome (`success`, `failed`, `skipped`, `missed`).
  - Only allowlisted agents and tools run (`scheduler.allowed_agents` / `allowed_tools`). Missed runs have a 180-minute grace window, and `DigestAutoplay` speaks the digest.
  - Installed on the user's Mac as the launchd agent `com.openjarvis.scheduler`. The digest task `a1c7a7d1d2b44f76` (cron `0 7 * * *`, Asia/Kolkata) first runs for real on 2026-10-12 at 07:00 IST.
- **D-016:** the import-count gate was dropped from architecture-review. **D-017:** paid down the D-015 debt:
  - `RunOutcome` / `RunRecord` replace the success flag, and `log_run` derives `success`.
  - The launchd plist is generated from intent (`restart="always"|"on_crash"`).
  - `BaseConnector.accepts_pasted_token` decides the `jarvis connect` paste flow.
- **Final cleanups this session:**
  - `jarvis connect` rejects a blank pasted token.
  - `SystemBuilder` and `jarvis operators logs` now use `open_default_store()`. They had ignored `OPENJARVIS_HOME` and `~`, which failed the architecture audit.
  - `jarvis operators logs` was broken: it called the nonexistent `get_runs`. It now uses `get_run_logs` and shows outcomes.
  - Skipped and missed runs show yellow instead of red, through the shared `cli/_run_outcome.py`.

## Gate results (2026-10-11T11:39Z, final tree, Cartesia env unset)

| Gate | Result |
|------|--------|
| `scripts/test.sh` | pass (9153 passed, 65 skipped) |
| `scripts/integration.sh` | pass (50 passed, 7 skipped) |
| `scripts/smoke.sh` | pass |
| `scripts/security.sh` | pass |
| `scripts/validate-harness.sh` | pass |
| `scripts/architecture-review.sh` | pass (LLM audit PASS) |
| `scripts/lint.sh` (soft) | pass |
| `scripts/code-review.sh` (soft) | ran and reviewed; no merge-blocking bugs |

## What remains

0. **F-025:** both spikes are done and `verified`. Findings are in `docs/spikes/whatsapp/FINDINGS.md`.
   - F-027: template text decodes; the body is at protobuf path `24.1.6`.
   - F-028: the launchd service reads WhatsApp data without Full Disk Access.
   Two design amendments were agreed:
   - D-027: drop `MARKETING`-category templates before the local model runs.
   - D-028: pre-approve profile-only senders of `UTILITY` templates, while keeping them reviewable.
   F-025 is ready: dispatch `Agent(subagent_type="orchestrator", prompt="F-025")`. The digest config needs `whatsapp_desktop` as a source, and the scheduler allowlists may need updating (D-011).
1. **Next feature the user wants:** text the digest to their phone. It needs design-consensus, and the messaging tool must be added to `scheduler.allowed_tools`.
2. F-023 (the web UI keeps a pasted Notion token in memory only) is `todo`. The code review notes the server still uses `hasattr(_token)` rather than `accepts_pasted_token`, so the CLI and the web UI disagree.
3. Code-review follow-ups (not done):
   - Commit or revert the `uv.lock` bumps separately (`datasets` 4→5, lock revision 3→5).
   - Notion `handle_callback` saves pasted tokens without validating them.
   - A relative `scheduler.db_path` resolves against the working directory (launchd runs from `/`).
   - A run interrupted by SIGTERM uses up its slot without leaving a log row.
   - The `log_run` signature change breaks external callers that pass `success=`.
   - "Start an unattended scheduler" should be one entry point. Today `SystemBuilder` can build a startable scheduler with no policy and no lock.
   - The plist does not carry `OPENJARVIS_HOME`.
   - Recurring tasks whose agent is not allowlisted log a skip on every slot.
4. Flaky test: `tests/server/test_deep_research_tools_wiring.py` once failed under `-n auto`. Its worker thread had not yet removed itself from `_managed_workers`. This code is not touched by the branch, and the test passes on rerun.
5. Known test-isolation issue: `tests/security/test_data_boundary_audit.py` fails when `CARTESIA_API_KEY` is exported. Run the gates with `env -u CARTESIA_API_KEY -u CARTESIA_VOICE_ID`.

## Blockers / decisions made

- D-001 to D-028 are in `docs/DECISION_LOG.md`. No open blockers. F-025's open questions are all resolved by spikes F-027 and F-028 and by D-027 and D-028.

## Files modified

- Source: F-021, F-022 and F-024 files (see `claude-progress.md` Sessions 4–6), plus this session's `cli/connect_cmd.py`, `cli/operators_cmd.py`, `cli/scheduler_cmd.py`, `cli/_run_outcome.py` (new) and `system/builder.py`.
- Tests: `tests/cli/test_connect.py`, `tests/cli/test_operators_logs.py` (new), `tests/scheduler/test_store.py`.
- Harness: `scripts/architecture-review.sh`, `docs/architecture-rules.md`, `docs/DECISION_LOG.md`, `feature_list.json`, `session-handoff.md`, `claude-progress.md`.
- Outside the repo: `~/.openjarvis/config.toml`, `credentials.toml`, `scheduler.db`, `prompts/personas/jarvis.md`, and `~/Library/LaunchAgents/com.openjarvis.scheduler.plist`.

## Benchmark results (if applicable)

None this session.

## Next session — start here

For F-025, dispatch the orchestrator (see "What remains" item 0). Also check that the 07:00 digest played on 2026-10-12, using `jarvis scheduler logs a1c7a7d1d2b44f76` and `~/.openjarvis/logs/scheduler.err.log`. Restart the service (`launchctl kickstart -k gui/$(id -u)/com.openjarvis.scheduler`) if it was started before this session's last edits. Then run design-consensus for "text me the digest".
