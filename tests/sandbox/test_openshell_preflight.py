"""Tests for the OpenShell pre-flight checks."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List

import pytest

from openjarvis.core.config import SandboxConfig
from openjarvis.sandbox.openshell_preflight import failures, preflight

IMAGE = "openshell/sandbox-from:1"


class FakeRun:
    def __init__(self, config_dir: Path) -> None:
        self.machine = {
            "Name": "openshell",
            "Rootful": True,
            "State": "running",
            "ConfigDir": {"Path": str(config_dir)},
        }
        self.machine_missing = False
        self.gateway_output = "Status: Connected\n"
        self.present_images: List[str] = [f"docker.io/{IMAGE}"]
        self.calls: List[List[str]] = []

    def __call__(self, argv, **_):
        self.calls.append(list(argv))
        if argv[:3] == ["podman", "machine", "inspect"]:
            if self.machine_missing:
                return _done(argv, 125, stderr="no such vm")
            return _done(argv, 0, json.dumps([self.machine]))
        if argv[:2] == ["openshell", "status"]:
            return _done(argv, 0, self.gateway_output)
        if "crictl" in argv:
            return _done(argv, 0 if argv[-1] in self.present_images else 1)
        raise AssertionError(f"unexpected command {argv}")


def _done(argv, rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr=stderr)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    (tmp_path / "openshell.json").write_text(json.dumps({"Mounts": []}))
    return tmp_path


@pytest.fixture
def run(config_dir) -> FakeRun:
    return FakeRun(config_dir)


def checks_by_name(run, **overrides) -> Dict[str, object]:
    sandbox = SandboxConfig(**{"runtime": "openshell", "image": IMAGE, **overrides})
    return {c.name: c for c in preflight(sandbox, run=run)}


def test_all_checks_pass_on_a_dedicated_rootful_machine(run):
    checks = checks_by_name(run)
    assert {c.status for c in checks.values()} == {"ok"}
    assert failures(checks.values()) == []


def test_missing_machine_fails(run):
    run.machine_missing = True
    check = checks_by_name(run)["OpenShell Podman machine"]
    assert check.status == "fail"
    assert "openshell" in check.detail


def test_rootless_machine_fails(run):
    run.machine["Rootful"] = False
    check = checks_by_name(run)["OpenShell Podman machine"]
    assert check.status == "fail"
    assert "rootful" in check.detail


def test_stopped_machine_fails(run):
    run.machine["State"] = "stopped"
    assert checks_by_name(run)["OpenShell Podman machine"].status == "fail"


def test_host_folders_mounted_is_a_warning_not_a_failure(run, config_dir):
    (config_dir / "openshell.json").write_text(
        json.dumps({"Mounts": [{"Source": "/Users", "Target": "/Users"}]})
    )
    checks = checks_by_name(run)
    check = checks["Host folders mounted in VM"]
    assert check.status == "warn"
    assert "/Users" in check.detail
    assert failures(checks.values()) == []


def test_gateway_not_connected_fails(run):
    run.gateway_output = "Status: Disconnected\n"
    assert checks_by_name(run)["OpenShell gateway"].status == "fail"


def test_image_is_not_blamed_when_the_gateway_is_down(run):
    run.gateway_output = "Status: Disconnected\n"
    check = checks_by_name(run)["Sandbox image"]
    assert check.status == "fail"
    assert "gateway" in check.detail
    assert "build-openshell-image.sh" not in check.detail
    assert not [c for c in run.calls if "crictl" in c]


def test_missing_image_fails_with_the_build_hint(run):
    run.present_images = []
    check = checks_by_name(run)["Sandbox image"]
    assert check.status == "fail"
    assert "build-openshell-image.sh" in check.detail


def test_image_is_looked_up_in_the_gateway_container_on_the_machine(run):
    checks_by_name(run, podman_machine="vm1", openshell_gateway="gw1")
    crictl = next(c for c in run.calls if "crictl" in c)
    assert crictl[:5] == [
        "podman",
        "--connection",
        "vm1-root",
        "exec",
        "openshell-cluster-gw1",
    ]


@pytest.mark.parametrize(
    ("image", "ref"),
    [
        ("openshell/sandbox-from:1", "docker.io/openshell/sandbox-from:1"),
        ("ghcr.io/org/img:2", "ghcr.io/org/img:2"),
        ("localhost/img:3", "localhost/img:3"),
        ("registry:5000/img", "registry:5000/img"),
    ],
)
def test_image_references_are_normalised_like_the_cluster(run, image, ref):
    run.present_images = [ref]
    assert checks_by_name(run, image=image)["Sandbox image"].status == "ok"


def test_missing_podman_binary_fails_instead_of_raising(config_dir):
    def missing(argv, **_):
        raise FileNotFoundError(argv[0])

    checks = {c.name: c for c in preflight(SandboxConfig(), run=missing)}
    assert checks["OpenShell Podman machine"].status == "fail"
    assert checks["OpenShell gateway"].status == "fail"
