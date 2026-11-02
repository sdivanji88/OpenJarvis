# Running Agents in OpenShell Sandboxes

With the OpenShell runtime, every agent run (chat, `jarvis ask`, scheduled tasks, the server) executes in a fresh [OpenShell](https://github.com/NVIDIA/OpenShell) sandbox instead of on your Mac. Each sandbox is used for one run and then deleted. Its network is deny-all apart from the hosts you allow for that agent. It holds no credentials. It reaches models only through the OpenShell inference gateway.

If OpenShell is not ready, runs are **refused** with a clear error. They never fall back to running on the host.

!!! warning "Model access is not wired up yet"
    Sandboxed agents call models through the OpenShell gateway, whose route to OpenJarvis arrives with feature F-031. Until then, sandboxed runs fail with `https://inference.local returned HTTP 503: cluster inference is not configured`. Leave `runtime` at its default unless you are working on the sandbox.

---

## Setup

You need [Podman](https://podman.io) and the `openshell` CLI (0.0.21 or later).

### 1. Create a dedicated Podman machine

OpenShell's gateway needs a **rootful** machine. By default Podman mounts `/Users` and `/private` read-write into its VM, so code that escaped a sandbox into the VM could reach your home directory. Use a separate machine with no host folders mounted:

```bash
podman machine init --rootful --cpus 4 --memory 8192 --disk-size 60 --volume "" openshell
```

On macOS only one Podman machine runs at a time, so stop the default one first:

```bash
podman machine stop podman-machine-default
podman machine start openshell
```

Start the machine from your own terminal (or a login item). A machine started by a short-lived script stops when that script exits.

### 2. Start the gateway on it

```bash
export DOCKER_HOST="unix://$(podman machine inspect openshell --format '{{.ConnectionInfo.PodmanSocket.Path}}')"
openshell gateway start
openshell status        # should report Connected
```

### 3. Build the sandbox image

```bash
scripts/build-openshell-image.sh
```

The script stages the OpenJarvis wheel and hash-checked Linux wheels from `uv.lock`. It then builds `deploy/openshell/` (digest-pinned `python:3.12-slim`, a `sandbox` user) and pushes the image into the gateway. It removes older images it built earlier, and prints the image to configure. Rebuild whenever OpenJarvis or its dependencies change.

### 4. Configure OpenJarvis

```toml
[sandbox]
runtime = "openshell"
image = "openshell/sandbox-from:1793544465"   # printed by the build script
timeout = 300
podman_machine = "openshell"                  # default
openshell_gateway = "openshell"               # default

[sandbox.allowed_hosts]
deep_research = ["api.example.com", "docs.example.com:8443"]

[sandbox.pool_sizes]
simple = 1      # keep one sandbox ready for chat
```

- **`allowed_hosts`**: per agent, the hosts (optionally `host:port`, default port 443) its sandbox may reach. Agents not listed get no network access.
- **`pool_sizes`**: per agent, how many sandboxes to keep ready. `0` (the default) creates one per run, which takes about 2 s. A ready sandbox starts a run in well under 100 ms.

### 5. Check it

```bash
jarvis doctor
```

With `runtime = "openshell"`, the doctor adds these rows:

| Check | Fails when |
|-------|------------|
| OpenShell Podman machine | the machine is missing, not rootful, or not running |
| Host folders mounted in VM | warns (does not fail) when the machine mounts host folders |
| OpenShell gateway | `openshell status` is not Connected |
| Sandbox image | the configured image is not in the gateway's cluster (or cannot be checked because the gateway is down) |

Any failing row means agent runs are refused. Runs are re-checked on the next attempt, so fixing the problem is enough; no restart is needed.

---

## How sandboxes are managed

- Sandboxes are named `oj-<process id>-<agent>-<random>`. At startup each OpenJarvis process deletes `oj-` sandboxes whose owning process is gone. The owner is the Python process, not a `uv run` wrapper around it. Sandboxes belonging to another running process (for example the scheduler while you use `jarvis ask`) are left alone.
- A ready sandbox is only handed to a run whose policy and image match exactly. Changing an agent's `allowed_hosts` or the image never reuses an old sandbox.
- On shutdown the process deletes its ready sandboxes. OpenShell takes about 35 s to terminate a pod after deletion.
- Host folders are never mounted into sandboxes. A run that asks for mounts or secrets is refused.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `OpenShell Podman machine: machine 'openshell' not found` | Create it (step 1), or set `[sandbox] podman_machine` to your machine's name. |
| `... is not rootful` | `podman machine stop openshell && podman machine set --rootful openshell && podman machine start openshell` |
| `Sandbox image: ... not in the cluster` | Run `scripts/build-openshell-image.sh` and update `[sandbox] image`. |
| Gateway fails with `/dev/kmsg: operation not permitted` | The machine is rootless; see above. |
| `OpenShell gateway: ... Connection refused` after `openshell gateway stop` or a machine restart | `podman --connection openshell-root start openshell-cluster-openshell`, then wait (about 2 min) for `openshell status` to report Connected. Run non-interactively, `openshell gateway start` reuses the stopped gateway without starting it, and `--recreate` wipes the cluster including the sandbox image. |
| `inference.local returned HTTP 503: cluster inference is not configured` | Model access through the gateway is not configured yet (F-031). |
