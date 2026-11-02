"""Checks that OpenShell can run sandboxed agents safely.

Used by the OpenShell runner (any ``fail`` refuses agent runs) and by
``jarvis doctor``. A broken image is reported by OpenShell as provisioning
forever, so the image is checked here rather than discovered at create time.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List

from openjarvis.core.config import SandboxConfig

Run = Callable[..., subprocess.CompletedProcess]

BUILD_HINT = "run scripts/build-openshell-image.sh and set [sandbox] image"
MACHINE_HINT = "see docs/user-guide/openshell-sandbox.md"


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # "ok", "warn" or "fail"
    detail: str


def failures(checks: Iterable[Check]) -> List[Check]:
    return [c for c in checks if c.status == "fail"]


def _call(run: Run, argv: List[str]) -> subprocess.CompletedProcess:
    try:
        return run(argv, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        return subprocess.CompletedProcess(argv, 127, "", f"{argv[0]} not found")
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"{argv[0]} timed out")


def _cluster_ref(image: str) -> str:
    first = image.split("/", 1)[0]
    if "/" in image and ("." in first or ":" in first or first == "localhost"):
        return image
    return f"docker.io/{image}"


def _machine_checks(sandbox: SandboxConfig, run: Run) -> List[Check]:
    name = sandbox.podman_machine
    machine_check = "OpenShell Podman machine"
    mounts_check = "Host folders mounted in VM"
    result = _call(run, ["podman", "machine", "inspect", name])
    if result.returncode != 0:
        detail = f"machine '{name}' not found ({result.stderr.strip()}); {MACHINE_HINT}"
        return [
            Check(machine_check, "fail", detail),
            Check(mounts_check, "warn", "unknown (machine not found)"),
        ]
    info = json.loads(result.stdout)[0]
    if not info.get("Rootful"):
        machine = Check(
            machine_check, "fail", f"'{name}' is not rootful; {MACHINE_HINT}"
        )
    elif info.get("State") != "running":
        machine = Check(machine_check, "fail", f"'{name}' is {info.get('State')}")
    else:
        machine = Check(machine_check, "ok", f"'{name}' is rootful and running")

    config_file = Path(info.get("ConfigDir", {}).get("Path", "")) / f"{name}.json"
    try:
        mounts = json.loads(config_file.read_text()).get("Mounts") or []
    except (OSError, ValueError):
        return [machine, Check(mounts_check, "warn", f"cannot read {config_file}")]
    if mounts:
        sources = ", ".join(m.get("Source", "?") for m in mounts)
        mounts_result = Check(
            mounts_check,
            "warn",
            f"{sources} visible inside the VM; a sandbox escape could reach them",
        )
    else:
        mounts_result = Check(mounts_check, "ok", "none")
    return [machine, mounts_result]


def _gateway_check(run: Run) -> Check:
    result = _call(run, ["openshell", "status"])
    if result.returncode == 0 and "Connected" in result.stdout:
        return Check("OpenShell gateway", "ok", "connected")
    reason = (result.stderr or result.stdout).strip() or "not connected"
    return Check("OpenShell gateway", "fail", reason)


def _image_check(sandbox: SandboxConfig, run: Run) -> Check:
    ref = _cluster_ref(sandbox.image)
    argv = [
        "podman", "--connection", f"{sandbox.podman_machine}-root",
        "exec", f"openshell-cluster-{sandbox.openshell_gateway}",
        "crictl", "inspecti", "-q", ref,
    ]  # fmt: skip
    if _call(run, argv).returncode == 0:
        return Check("Sandbox image", "ok", sandbox.image)
    return Check(
        "Sandbox image", "fail", f"{sandbox.image} not in the cluster; {BUILD_HINT}"
    )


def preflight(sandbox: SandboxConfig, *, run: Run = subprocess.run) -> List[Check]:
    return [
        *_machine_checks(sandbox, run),
        _gateway_check(run),
        _image_check(sandbox, run),
    ]


__all__ = ["Check", "failures", "preflight"]
