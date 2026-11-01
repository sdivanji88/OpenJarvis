# OpenShell spikes (F-029)

Run on 2026-11-01 on the developer's Mac mini (Apple Silicon, macOS 26) with
OpenShell 0.0.21 and Podman 6.0.2. Only dummy credentials were used.

## Baseline

- `openshell --version`: `openshell 0.0.21`
- `openshell status`: Gateway `openshell`, server `https://127.0.0.1:8080`, `Connected`, version `0.0.21`
- `openshell doctor check`: Docker ok (version 6.0.2), all checks passed
- Podman machine: 4 CPUs, 8 GiB memory (`podman-machine-default`, `applehv`), **rootful**
- `DOCKER_HOST` must point at the Podman machine API socket
  (`unix:///var/folders/.../podman/podman-machine-default-api.sock`); OpenShell does not find Podman without it.

### Finding B1: the gateway needs a rootful Podman machine

With the default rootless Podman machine, `openshell gateway start` fails with
`K8s namespace not ready`. The gateway runs k3s inside a container, and the
kubelet exits with:

```
Failed to create an oomWatcher (running in UserNS ...) err="open /dev/kmsg: operation not permitted"
Error: failed to run Kubelet: failed to create kubelet: open /dev/kmsg: operation not permitted
```

`openshell doctor check` still reports "All checks passed" in that state, so
it does not detect the problem. Fix: `podman machine stop && podman machine set
--rootful && podman machine start`, then `openshell gateway destroy --name
openshell && openshell gateway start`. Containers then run as root inside the
Linux VM, which is still isolated from macOS by the VM.

Implication for F-030: `jarvis doctor` must check for a rootful Podman machine
(`podman info --format '{{.Host.Security.Rootless}}'` is `false`) and a
reachable gateway, and report the fix above. A Podman VM started from a
short-lived process can be killed when that process exits; the VM must be
started from a long-lived session (or a launchd agent).

## Q1. How long does creating a sandbox take?
## Q2. Can a pooled deny-all sandbox reach the network before its policy is applied?
## Q3. Does `openshell policy set` change a live sandbox's network policy?
## Q4. Can a provider be attached after a sandbox is created?
## Q5. Can the inference gateway forward to OpenJarvis `/v1`, and can that endpoint be limited to the gateway?
## Q6. How does the host run a command in an existing sandbox and read clean output?
## Q7. How are spike / orphaned sandboxes identified and removed?
## Implications for F-030 – F-033
