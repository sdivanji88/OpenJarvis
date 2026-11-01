"""Tests for the OpenShell runner."""

from __future__ import annotations

import json
import subprocess
from typing import Callable, Dict, List, Optional

import pytest

from openjarvis.core.config import SandboxConfig
from openjarvis.sandbox.openshell_cli import OpenShellError, SandboxTimeout
from openjarvis.sandbox.openshell_policy import build_policy, render_policy
from openjarvis.sandbox.openshell_runner import OpenShellRunner, shared_runner

START = "---OPENJARVIS_OUTPUT_START---"
END = "---OPENJARVIS_OUTPUT_END---"


class FakeShell:
    """In-memory OpenShell: sandboxes plus a scripted agent process."""

    def __init__(self, existing: Optional[List[str]] = None) -> None:
        self.sandboxes: Dict[str, str] = {n: "" for n in existing or []}
        self.ready = True
        self.create_error: Optional[str] = None
        self.execs: List[dict] = []
        self.agent: Callable[[dict], subprocess.CompletedProcess] = lambda req: _done(
            f"{START}{json.dumps({'content': 'ok:' + req['prompt']})}{END}"
        )

    def create(self, name: str, policy: str) -> None:
        if self.create_error:
            raise OpenShellError(self.create_error)
        self.sandboxes[name] = policy

    def delete(self, name: str) -> None:
        self.sandboxes.pop(name, None)

    def list_names(self) -> List[str]:
        return list(self.sandboxes)

    def gateway_ready(self) -> bool:
        return self.ready

    def exec(self, name, command, *, input, timeout):
        assert name in self.sandboxes, "exec on a deleted sandbox"
        self.execs.append(
            {"name": name, "command": command, "timeout": timeout,
             "policy": self.sandboxes[name], "request": json.loads(input)}
        )  # fmt: skip
        return self.agent(json.loads(input))


def _done(stdout="", rc=0, stderr=""):
    return subprocess.CompletedProcess([], rc, stdout=stdout, stderr=stderr)


@pytest.fixture
def shell() -> FakeShell:
    return FakeShell()


def make_runner(shell, **kwargs) -> OpenShellRunner:
    kwargs.setdefault("image_id", "sha256:aaa")
    return OpenShellRunner(shell, **kwargs)


def request(agent="chat", prompt="hi") -> dict:
    return {"prompt": prompt, "agent_id": agent, "model": "m"}


class TestRun:
    def test_run_returns_the_agent_output(self, shell):
        result = make_runner(shell).run(request(prompt="hello"))
        assert result == {"content": "ok:hello"}

    def test_run_sends_the_request_to_the_sandbox(self, shell):
        make_runner(shell).run(request(prompt="hello"), workspace="/sandbox/w")
        sent = shell.execs[0]["request"]
        assert sent["prompt"] == "hello"
        assert sent["_workspace"] == "/sandbox/w"

    def test_run_uses_the_agents_generated_policy(self, shell):
        runner = make_runner(shell, allowed_hosts={"digest": ["api.example.com"]})
        runner.run(request(agent="digest"))
        expected = render_policy(build_policy(["api.example.com"]))
        assert shell.execs[0]["policy"] == expected

    def test_unknown_agent_gets_the_deny_all_policy(self, shell):
        make_runner(shell).run(request(agent="other"))
        assert shell.execs[0]["policy"] == render_policy(build_policy([]))

    def test_sandbox_is_deleted_after_the_run(self, shell):
        make_runner(shell).run(request())
        assert shell.sandboxes == {}

    def test_sandbox_is_deleted_when_the_agent_fails(self, shell):
        shell.agent = lambda req: _done(rc=1, stderr="boom")
        result = make_runner(shell).run(request())
        assert result["error"] is True
        assert "boom" in result["content"]
        assert shell.sandboxes == {}

    def test_env_is_passed_to_the_agent_command(self, shell):
        make_runner(shell, command="agent").run(request(), env={"A": "x y"})
        assert shell.execs[0]["command"] == "env A='x y' agent"

    def test_invalid_env_names_are_refused(self, shell):
        result = make_runner(shell).run(request(), env={"A;rm -rf /": "x"})
        assert result["error"] is True
        assert shell.execs == []

    def test_output_without_sentinels_is_returned_as_content(self, shell):
        shell.agent = lambda req: _done("plain text\n")
        assert make_runner(shell).run(request()) == {"content": "plain text"}


class TestFailClosed:
    def test_create_failure_is_reported_and_nothing_runs(self, shell):
        shell.create_error = "gateway unreachable"
        result = make_runner(shell).run(request())
        assert result["error"] is True
        assert result["error_type"] == "sandbox_unavailable"
        assert "gateway unreachable" in result["content"]
        assert shell.execs == []

    def test_timeout_is_reported_and_the_sandbox_deleted(self, shell):
        def hang(req):
            raise SandboxTimeout("ssh timed out")

        shell.agent = hang
        result = make_runner(shell, timeout=7).run(request())
        assert result["error_type"] == "timeout"
        assert shell.execs[0]["timeout"] == 7
        assert shell.sandboxes == {}

    def test_host_mounts_are_refused(self, shell):
        result = make_runner(shell).run(request(), mounts=["/Users/me"])
        assert result["error"] is True
        assert shell.execs == []

    def test_secrets_are_refused(self, shell):
        result = make_runner(shell).run(request(), secrets={"TOKEN": "t"})
        assert result["error"] is True
        assert shell.execs == []

    def test_start_refuses_when_the_gateway_is_down(self, shell):
        shell.ready = False
        with pytest.raises(OpenShellError, match="gateway"):
            make_runner(shell).start()


class TestLifecycle:
    def test_start_cleans_up_orphans_and_warms_pools(self):
        shell = FakeShell(existing=["oj-chat-old", "other"])
        make_runner(shell, pool_sizes={"chat": 1}).start()
        names = list(shell.sandboxes)
        assert "oj-chat-old" not in names
        assert "other" in names
        assert len([n for n in names if n.startswith("oj-chat-")]) == 1

    def test_run_uses_the_warm_sandbox(self, shell):
        runner = make_runner(shell, pool_sizes={"chat": 1})
        runner.start()
        warm = next(n for n in shell.sandboxes if n.startswith("oj-"))
        runner.run(request())
        assert shell.execs[0]["name"] == warm

    def test_shutdown_leaves_no_prefixed_sandboxes(self, shell):
        runner = make_runner(shell, pool_sizes={"chat": 2})
        runner.start()
        runner.shutdown()
        assert not [n for n in shell.sandboxes if n.startswith("oj-")]

    def test_close_shuts_down(self, shell):
        runner = make_runner(shell, pool_sizes={"chat": 1})
        runner.start()
        runner.close()
        assert shell.sandboxes == {}


class TestSharedRunner:
    @pytest.fixture(autouse=True)
    def _fresh(self):
        shared_runner.cache_clear()
        yield
        shared_runner.cache_clear()

    def config(self, **overrides) -> SandboxConfig:
        return SandboxConfig(runtime="openshell", image="img@sha256:1", **overrides)

    def test_none_unless_runtime_is_openshell(self):
        assert shared_runner(SandboxConfig(runtime="docker")) is None

    def test_one_started_runner_per_config(self):
        shells: List[FakeShell] = []

        def make_shell(image: str) -> FakeShell:
            shells.append(FakeShell())
            return shells[-1]

        config = self.config(pool_sizes={"chat": 1})
        first = shared_runner(config, shell_factory=make_shell)
        second = shared_runner(config, shell_factory=make_shell)
        assert first is second
        assert len(shells) == 1
        assert [n for n in shells[0].sandboxes if n.startswith("oj-chat-")]
        first.shutdown()

    def test_gateway_down_still_returns_a_runner_that_fails_closed(self):
        shell = FakeShell()
        shell.ready = False
        shell.create_error = "connection refused"
        runner = shared_runner(self.config(), shell_factory=lambda image: shell)
        result = runner.run(request())
        assert result["error_type"] == "sandbox_unavailable"
