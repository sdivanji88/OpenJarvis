"""Tests for the OpenShell CLI adapter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable, Dict, List

import pytest

from openjarvis.sandbox.openshell_cli import (
    OpenShellCLI,
    OpenShellError,
    SandboxTimeout,
)

SSH_CONFIG = "Host openshell-{name}\n  ProxyCommand openshell ssh-proxy {name}\n"


class FakeRun:
    """Records argv and answers like the openshell and ssh binaries."""

    def __init__(self) -> None:
        self.calls: List[List[str]] = []
        self.inputs: List[str | None] = []
        self.policies: Dict[str, dict] = {}
        self.handlers: Dict[
            str, Callable[[List[str]], subprocess.CompletedProcess]
        ] = {}

    def __call__(self, argv, *, input=None, timeout=None, **_):
        self.calls.append(list(argv))
        self.inputs.append(input)
        verb = " ".join(argv[1:3]) if argv[0] == "openshell" else argv[0]
        if verb in self.handlers:
            return self.handlers[verb](argv)
        if verb == "sandbox create":
            name = argv[argv.index("--name") + 1]
            self.policies[name] = json.loads(
                Path(argv[argv.index("--policy") + 1]).read_text()
            )
            return _done(argv, stdout="Created sandbox\n")
        if verb == "sandbox ssh-config":
            return _done(argv, stdout=SSH_CONFIG.format(name=argv[3]))
        return _done(argv)

    def commands(self, verb: str) -> List[List[str]]:
        return [c for c in self.calls if " ".join(c[1:3]) == verb]


def _done(argv, rc=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr=stderr)


@pytest.fixture
def run() -> FakeRun:
    return FakeRun()


@pytest.fixture
def cli(run, tmp_path) -> OpenShellCLI:
    return OpenShellCLI(image="oj-sandbox@sha256:abc", run=run, state_dir=tmp_path)


class TestCreate:
    def test_create_passes_image_policy_and_no_providers(self, cli, run):
        cli.create("oj-chat-1", '{"version": 1}')
        argv = run.commands("sandbox create")[0]
        assert argv[argv.index("--from") + 1] == "oj-sandbox@sha256:abc"
        assert "--no-auto-providers" in argv
        assert "--no-tty" in argv
        assert run.policies["oj-chat-1"] == {"version": 1}

    def test_create_keeps_the_sandbox_alive_for_ssh(self, cli, run):
        cli.create("oj-chat-1", "{}")
        argv = run.commands("sandbox create")[0]
        assert argv[-2:] == ["--", "true"]

    def test_failed_create_raises_and_deletes_the_partial_sandbox(self, cli, run):
        run.handlers["sandbox create"] = lambda a: _done(a, rc=1, stderr="no image")
        with pytest.raises(OpenShellError, match="no image"):
            cli.create("oj-chat-1", "{}")
        assert run.commands("sandbox delete")[0][-1] == "oj-chat-1"

    def test_create_timeout_raises_and_deletes(self, cli, run):
        def hang(argv):
            raise subprocess.TimeoutExpired(argv, 120)

        run.handlers["sandbox create"] = hang
        with pytest.raises(OpenShellError, match="timed out"):
            cli.create("oj-chat-1", "{}")
        assert run.commands("sandbox delete")[0][-1] == "oj-chat-1"


class TestExec:
    def test_exec_runs_over_ssh_with_the_sandbox_config(self, cli, run):
        cli.create("oj-chat-1", "{}")
        run.handlers["ssh"] = lambda a: _done(a, stdout="out")
        result = cli.exec("oj-chat-1", "python -m agent", input="{}", timeout=60)
        argv = run.calls[-1]
        assert argv[0] == "ssh"
        assert argv[-2:] == ["openshell-oj-chat-1", "python -m agent"]
        config = Path(argv[argv.index("-F") + 1]).read_text()
        assert "Host openshell-oj-chat-1" in config
        assert run.inputs[-1] == "{}"
        assert result.stdout == "out"

    def test_exec_on_unknown_sandbox_raises(self, cli):
        with pytest.raises(OpenShellError, match="unknown sandbox"):
            cli.exec("oj-missing", "true", input="", timeout=5)

    def test_exec_timeout_raises(self, cli, run):
        cli.create("oj-chat-1", "{}")

        def hang(argv):
            raise subprocess.TimeoutExpired(argv, 5)

        run.handlers["ssh"] = hang
        with pytest.raises(SandboxTimeout, match="timed out"):
            cli.exec("oj-chat-1", "true", input="", timeout=5)


class TestDeleteAndList:
    def test_delete_removes_the_ssh_config(self, cli, run, tmp_path):
        cli.create("oj-chat-1", "{}")
        cli.delete("oj-chat-1")
        assert run.commands("sandbox delete")[-1][-1] == "oj-chat-1"
        assert not list(tmp_path.glob("*oj-chat-1*"))

    def test_delete_failure_does_not_raise(self, cli, run):
        run.handlers["sandbox delete"] = lambda a: _done(a, rc=1, stderr="gone")
        cli.delete("oj-chat-1")

    def test_list_names_returns_non_blank_lines(self, cli, run):
        run.handlers["sandbox list"] = lambda a: _done(a, stdout="oj-a\n\noj-b\n")
        assert cli.list_names() == ["oj-a", "oj-b"]
        assert "--names" in run.commands("sandbox list")[0]


class TestGateway:
    def test_gateway_ready_when_status_is_connected(self, cli, run):
        run.handlers["status"] = lambda a: _done(a, stdout="Status: Connected\n")
        assert cli.gateway_ready() is True

    def test_gateway_not_ready_when_status_fails(self, cli, run):
        run.handlers["status"] = lambda a: _done(a, rc=1, stderr="refused")
        assert cli.gateway_ready() is False

    def test_gateway_not_ready_when_binary_missing(self, tmp_path):
        def missing(argv, **_):
            raise FileNotFoundError(argv[0])

        cli = OpenShellCLI(image="x", run=missing, state_dir=tmp_path)
        assert cli.gateway_ready() is False
