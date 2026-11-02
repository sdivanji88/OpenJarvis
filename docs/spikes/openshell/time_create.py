"""Time OpenShell sandbox creation and deletion (F-029 Q1).

Create (until the sandbox ran `true` and is Ready), first SSH command, and
delete are timed separately, because they land on different paths in a
warm pool: create and first SSH happen while warming, delete after the run.

Usage: python3 docs/spikes/openshell/time_create.py <from> <runs> [policy.yaml]
Example: python3 docs/spikes/openshell/time_create.py base 5 docs/spikes/openshell/policies/deny_all.yaml
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import tempfile
import time


def _timed(cmd: list[str]) -> float:
    start = time.monotonic()
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return time.monotonic() - start


def one_run(source: str, name: str, policy: str | None) -> tuple[float, float, float]:
    create = ["openshell", "sandbox", "create", "--name", name, "--from", source,
              "--no-tty", "--no-auto-providers"]
    if policy:
        create += ["--policy", policy]
    t_create = _timed(create + ["--", "true"])

    ssh_config = subprocess.run(
        ["openshell", "sandbox", "ssh-config", name],
        check=True, capture_output=True, text=True,
    ).stdout
    with tempfile.NamedTemporaryFile("w", suffix=".conf") as conf:
        conf.write(ssh_config)
        conf.flush()
        t_ssh = _timed(["ssh", "-F", conf.name, f"openshell-{name}", "true"])

    t_delete = _timed(["openshell", "sandbox", "delete", name])
    return t_create, t_ssh, t_delete


def _summary(label: str, values: list[float]) -> str:
    return (f"{label:<10} median {statistics.median(values):5.1f}s  "
            f"min {min(values):5.1f}s  max {max(values):5.1f}s")


def main() -> None:
    source, runs = sys.argv[1], int(sys.argv[2])
    policy = sys.argv[3] if len(sys.argv) > 3 else None
    results = [one_run(source, f"oj-spike-time-{i}", policy) for i in range(runs)]
    print(f"source={source} runs={runs} policy={policy}")
    for i, (c, s, d) in enumerate(results):
        print(f"  run {i}: create {c:5.1f}s  first-ssh {s:5.1f}s  delete {d:5.1f}s")
    print(_summary("create", [r[0] for r in results]))
    print(_summary("first-ssh", [r[1] for r in results]))
    print(_summary("delete", [r[2] for r in results]))


if __name__ == "__main__":
    main()
