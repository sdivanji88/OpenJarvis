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

### Finding B2: the `python` community image is not public; `base` is 1.13 GB

`openshell sandbox create --from python` (the example in OpenShell's own help)
fails: the cluster gets `403 Forbidden` from ghcr.io when requesting an
anonymous pull token for `nvidia/openshell-community/sandboxes/python`.
`base`, `openclaw` and `ollama` return 200. The spike uses `--from base`
instead of `--from python` throughout (deviation from the plan).

`base:latest` is 1,127 MB compressed (arm64, 13 layers). On this connection
the first pull took **29 min 20 s** (`Successfully pulled image ... in
29m19.995s`). `sandbox create` gives up after **300 s**
(`sandbox provisioning timed out after 300s ... DependenciesNotReady`) while
the cluster keeps pulling in the background, and the stuck sandbox stays
listed as `Provisioning` until deleted. The very first sandbox on a fresh
gateway also waited 145 s for compute.

Implication for F-030: the image must be pre-pulled (or built and pushed)
before the pool starts, outside any request path; `jarvis doctor` should
report whether the sandbox image is present in the cluster. A slim
OpenJarvis image matters: every megabyte is paid on first pull.

## Q1. How long does creating a sandbox take?
## Q2. Can a pooled deny-all sandbox reach the network before its policy is applied?

**Verdict: CONFIRMED that it cannot.** A sandbox created with
`--policy deny_all.yaml` (`network_policies: {}`) blocks every destination
from its very first command:

```
openshell sandbox create --name oj-spike-deny --from base --no-tty --no-auto-providers \
  --policy docs/spikes/openshell/policies/deny_all.yaml \
  --upload docs/spikes/openshell/net_probe.sh:/sandbox -- \
  sh /sandbox/net_probe.sh https://example.com https://pypi.org http://host.containers.internal:11434/api/tags
BLOCKED https://example.com
BLOCKED https://pypi.org
BLOCKED http://host.containers.internal:11434/api/tags
```

Control, same command without `--policy` (OpenShell's default policy):

```
BLOCKED https://example.com
ALLOWED https://pypi.org
BLOCKED http://host.containers.internal:11434/api/tags
```

So the probe can tell the two apart, and enforcement is active from the
first command even though `policy get` on a fresh sandbox shows version 1 as
`Status: Pending, Active: 0`.

Other observations:

- **Network rules are scoped to binaries.** Each rule in
  `network_policies` lists allowed `endpoints` (host, port, optional L7
  `protocol: rest` with method/path rules and `access: read-only`) *and* the
  `binaries` allowed to use them. The default allows PyPI only for the
  sandbox venv Python, pip and uv. The probe therefore uses
  `/sandbox/.venv/bin/python3`.
- **The default policy is permissive** for an untrusted agent: Anthropic,
  OpenAI, GitHub (including git push paths for copilot), PyPI, Cursor,
  VS Code and NVIDIA endpoints. OpenJarvis must always pass its own policy.
- **`--upload <file>:<file path>` at create time silently uploads nothing**
  (it prints "Files uploaded"). `--upload <file>:/sandbox` (a directory) and
  `openshell sandbox upload <name> <file> <dir>` both work.
- The first SSH connection to a newly created sandbox took 34 s; later
  connections to the same sandbox took ~20 ms.

Implication for F-030: create pool sandboxes with an explicit deny-all
policy; never rely on OpenShell's default. Policy generation (D-035) must
emit binary-scoped rules, so `[sandbox.agents.<id>]` needs to know which
binaries the agent's tools use (at minimum the sandbox Python). Always upload
to a directory, then verify the file exists. Open the first SSH connection
while warming the pool, not on the request path.
## Q3. Does `openshell policy set` change a live sandbox's network policy?

**Verdict: CONFIRMED, but it takes 2–10 s.** On the live `oj-spike-deny`
sandbox (probed over SSH; the curl line checks binary scoping):

```
--- 1. deny-all
BLOCKED https://example.com
BLOCKED https://pypi.org
BLOCKED curl https://example.com
--- 2. openshell policy set --policy allow_example.yaml --wait oj-spike-deny
✓ Policy version 4 loaded (active version: 4)      real 8.05
ALLOWED https://example.com
BLOCKED https://pypi.org
BLOCKED curl https://example.com
--- 3. openshell policy set --policy deny_all.yaml --wait oj-spike-deny
✓ Policy version 5 loaded (active version: 5)      real 9.05
BLOCKED https://example.com
BLOCKED https://pypi.org
BLOCKED curl https://example.com
```

Policies can be loosened and tightened on a live sandbox. `openshell policy
list` keeps the full revision history (`Loaded` / `Superseded`).

**Binary matching uses the resolved executable.** The first attempt listed
only `/sandbox/.venv/bin/python3` and stayed blocked although the policy had
loaded. `openshell logs` showed why:

```
CONNECT action=deny binary=/sandbox/.uv/python/cpython-3.14.3-linux-aarch64-gnu/bin/python3.14
  cmdline=/sandbox/.venv/bin/python3, /sandbox/net_probe.sh dst_host=example.com dst_port=443
  reason=binary '/sandbox/.uv/python/.../python3.14' ... not allowed in policy 'example'
```

Adding `/sandbox/.uv/python/**` fixed it. Every denial is logged with binary,
ancestors, command line, destination and reason, and the sandbox sends
"denial analysis" proposals to the gateway.

**Latency.** `policy set --wait` took 2.0, 6.0, 8.1, 9.1 and 10.1 s across
five changes. The sandbox picks up changes on a settings poll
(`Settings poll: config change detected ... policy_changed=true`), so the
wait is up to one poll interval (about 10 s).

Implication for F-030: applying the agent's policy at claim time (D-031)
puts up to ~10 s on every run, including chat, which defeats the warm pool.
Options for a design revisit: per-agent pools created with the agent's
policy (`--policy` at create time costs nothing extra), or pre-applying a
policy to a pooled sandbox before it is claimed. Generated policies must
list resolved executables (e.g. `/sandbox/.uv/python/**`), and `openshell
logs` denials should be surfaced in OpenJarvis's audit log.
## Q4. Can a provider be attached after a sandbox is created?

**Verdict: REFUTED, but providers turn out to be much stronger than uploaded
tokens.** There is no command to attach a provider to a running sandbox
(`openshell sandbox --help`: create/get/list/delete/connect/upload/download/
ssh-config; `openshell settings` holds only key/value settings). And a
provider's credential is **fixed at sandbox creation**: after
`openshell provider update oj-spike-dummy --credential SPIKE_TOKEN=spike-dummy-token-ROTATED`,
the running `oj-spike-subst` still sent the old value (checked for over 30 s),
while a sandbox created afterwards sent `...-ROTATED`.

**Credentials never enter the sandbox.** With `--provider oj-spike-dummy`
(a `generic` provider holding `SPIKE_TOKEN`), the sandbox sees only a
placeholder, and no file contains the value:

```
SPIKE_TOKEN=openshell:resolve:env:SPIKE_TOKEN
HTTPS_PROXY=http://10.200.0.1:3128   (all egress goes through the OpenShell proxy)
```

The proxy swaps the placeholder for the real value on the way out, for
endpoints with `tls: terminate` (`policies/allow_echo.yaml`, httpbin.org):

```
in-sandbox value: openshell:resolve:env:SPIKE_TOKEN
curl -H "Authorization: Bearer $SPIKE_TOKEN" -H "X-Spike: $SPIKE_TOKEN" https://httpbin.org/headers
  "Authorization": "Bearer spike-dummy-token-not-a-secret"
  "X-Spike": "spike-dummy-token-not-a-secret"
curl -X POST -d "{\"body_field\": \"$SPIKE_TOKEN\"}" "https://httpbin.org/post?q=$SPIKE_TOKEN"
  "q": "spike-dummy-token-not-a-secret"                 (URL query: substituted)
  "body_field": "openshell:resolve:env:SPIKE_TOKEN"     (body: NOT substituted)
```

Substitution happens in **every header and in the URL query**, not in
request bodies. An injected agent cannot read the token, but it could leak
it to an allowed host that echoes or stores headers or URLs it receives.

Fallback, uploaded token file: `openshell sandbox upload oj-spike-pool1 <token> /sandbox/.oj`
works, and `chmod 600` applies, but the file is owned by `sandbox`, the same
user the agent runs as (`uid=998(sandbox)`), so the agent can read the token
in plain text.

Implication for F-032 / D-034: use OpenShell providers, not uploaded files.
That is stronger than the agreed design (the agent never holds the token).
Because credentials are fixed at creation, a pooled sandbox carries the
token minted when it was created: either the pool is per agent (created with
that agent's providers and refilled before tokens expire), or sandboxes for
agents with credentials are created at claim time. Allowed hosts for
credentialed agents must not reflect headers or URLs (no httpbin-like
endpoints, no user-controlled redirects).
## Q5. Can the inference gateway forward to OpenJarvis `/v1`, and can that endpoint be limited to the gateway?

**Verdict: CONFIRMED.** Setup: `jarvis serve --host 127.0.0.1 --port 8000
-m qwen3.5:2b` with a throwaway `OPENJARVIS_API_KEY` (401 without it), then:

```
openshell provider create --name oj-spike-jarvis --type openai \
  --credential OPENAI_API_KEY=<throwaway key> \
  --config OPENAI_BASE_URL=http://host.openshell.internal:8000/v1
openshell inference set --provider oj-spike-jarvis --model qwen3.5:2b
  Validated Endpoints: http://host.openshell.internal:8000/v1/chat/completions (openai_chat_completions)
```

`http://host.containers.internal:8000/v1` failed verification ("failed to
connect"). The gateway runs as a Kubernetes pod inside the cluster
container, and inside that pod only `host.docker.internal` and
`host.openshell.internal` resolve (both to `192.168.127.254`, the Podman
host gateway, which forwards to the Mac's loopback). A loopback-only bind is
enough.

From a **deny-all** sandbox with no keys, `infer_probe.py` calls
`https://inference.local/v1/chat/completions` with no Authorization header:

```
env vars named *KEY*/*TOKEN*: []
status 200 14.8s            (first call: model load + 13k-token prompt)
model qwen3.5:2b usage {'prompt_tokens': 13351, 'completion_tokens': 2, 'total_tokens': 13353}
content ok
```

Warm calls: 0.2 s through `inference.local` and 0.21–0.22 s calling
`jarvis serve` directly, so the gateway adds no measurable latency.
`inference.local` is not in any policy and does not resolve via DNS; the
OpenShell proxy handles it, even under `network_policies: {}`.

Telemetry: `~/.openjarvis/telemetry.db` went from 37 to 38 rows; the new
row is `model_id=qwen3.5:2b engine=ollama prompt_tokens=13351
completion_tokens=2 latency_seconds=14.69`. (The gateway's two verification
calls also wrote rows 36–37.)

Restricting `/v1` to the gateway: a deny-all sandbox cannot reach it
directly:

```
BLOCKED http://host.openshell.internal:8000/v1/models
BLOCKED http://host.containers.internal:8000/v1/models
BLOCKED http://host.docker.internal:11434/api/tags
```

The endpoint stays bound to loopback (not reachable from the LAN), and the
API key lives only in the gateway's provider, so sandboxes never see it.
Other processes on the Mac and other containers in the Podman VM can still
reach it, but only with the key.

Other observations:

- `energy_joules` is 0 on all 38 rows, before and after the spike. Energy
  telemetry is not enabled in this setup; that is unrelated to the sandbox.
- A one-line question cost 13,351 prompt tokens: `jarvis serve`'s
  `/v1/chat/completions` wraps requests in an agent with a large system
  prompt and tools. Sandboxed agents run their own loop, so the gateway's
  upstream should be a plain engine pass-through, not an agent.
- The gateway route is gateway-wide (one provider + model for all
  sandboxes), and **the gateway forces its configured model**: a request for
  `qwen3:0.6b` was answered by `qwen3.5:2b` (response `model` and the
  telemetry row both say `qwen3.5:2b`). Per-agent model choice is not
  possible through this route.
- `--no-keep` combined with `ssh-config` in a process substitution
  (`-F <(...)`) fails; write the SSH config to a file.

Implication for F-031 / D-033: the agreed design works as specified. F-031
needs a pass-through mode for the host endpoint (no agent wrapping). Because
the gateway forces one model for every sandbox, OpenJarvis's per-agent model
and local-versus-cloud routing can only happen on the host side of the
gateway (the host endpoint picks the engine), and the request's `model`
field cannot carry that choice. The `agent` column is empty, so sandboxed
calls need another way to be tagged with the agent that made them.
## Q6. How does the host run a command in an existing sandbox and read clean output?

**Verdict: CONFIRMED (over SSH).**

One-shot (`--no-keep`), image cached:

```
openshell sandbox create --name oj-spike-oneshot --from base --no-keep --no-tty --no-auto-providers -- \
  sh -c 'command -v python3; python3 -c "print(START); print({\"ok\": true}); print(END)"'
exit=0, 34.0 s total (create + run + delete)
```

Stdout contained OpenShell's own progress lines with ANSI colour codes
(`Created sandbox: ...`, `[0.0s] Requesting compute...`, `✓ Deleted sandbox ...`)
interleaved with the command's output; stderr was empty. The sentinel lines
came back intact, and `python3` is `/sandbox/.venv/bin/python3`. `--no-keep`
deleted the sandbox (`openshell sandbox list` → `No sandboxes found.`).

Pooled sandbox, driven over SSH:

```
openshell sandbox create --name oj-spike-pool1 --from base --no-tty --no-auto-providers -- true   # 2.3 s, phase Ready, stays alive
openshell sandbox ssh-config oj-spike-pool1 > ssh.conf
# Host openshell-oj-spike-pool1, User sandbox, ProxyCommand openshell ssh-proxy --gateway-name openshell --name oj-spike-pool1
echo '{"prompt":"hi"}' | ssh -F ssh.conf openshell-oj-spike-pool1 'cat; echo; echo done'
# stdout: {"prompt":"hi"} / done ; stderr empty ; exit 0
ssh -F ssh.conf openshell-oj-spike-pool1 'exit 7'   # exit status 7 propagated
```

Five `ssh ... 'echo ok'` round trips: 0.02–0.03 s each.

**`RUN_IN(name, cmd)`** = `ssh -F <ssh-config for name> openshell-<name> '<cmd>'`,
with the payload on stdin. Stdout is clean (only the command's output) and
the remote exit code is propagated.

Implication for F-030: drive pooled sandboxes over SSH, not through
`sandbox create -- <cmd>`, whose stdout mixes in OpenShell's progress lines.
Keep the sentinel markers anyway as a guard.
## Q7. How are spike / orphaned sandboxes identified and removed?

**Verdict: CONFIRMED, by name prefix only.** `openshell sandbox list` has
`--names` / `--ids` (one per line) but no labels, filters or JSON output, so
the name prefix is the only handle. This worked:

```
openshell sandbox list --names | grep '^oj-spike-' | xargs -n1 openshell sandbox delete
✓ Deleted sandbox oj-spike-pool1   (… six sandboxes)
```

Deletion is asynchronous. The sandboxes disappear from `sandbox list` at
once, but their Kubernetes pods stay `Terminating` for about **35 s** (the
default 30 s grace period). That is also why the `--no-keep` one-shot in Q6
took 34 s in total. `time_create.py` measured `sandbox delete` returning in
under 0.1 s.

Leftovers that `sandbox delete` does not cover:

- Providers (`openshell provider delete <name>`).
- The gateway-wide inference route: after `provider delete oj-spike-jarvis`,
  `openshell inference get` still shows `Provider: oj-spike-jarvis`, and
  there is no `inference delete` command. It has to be overwritten with
  `inference set`.

Implication for F-030: name every OpenJarvis sandbox with a fixed prefix
(e.g. `oj-<agent>-<id>`) and clean up by prefix at startup. Never put the
30 s pod termination on the request path: release returns immediately, and
the pool counts terminating pods against the Podman VM's capacity (4 CPUs,
8 GiB here). The host must own the inference route and reset it with
`inference set` at startup.
## Implications for F-030 – F-033
