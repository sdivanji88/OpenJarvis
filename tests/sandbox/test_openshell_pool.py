"""Tests for the OpenShell sandbox pool."""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List

import pytest

from openjarvis.sandbox.openshell_pool import SandboxPool


class FakeOpenShell:
    """In-memory stand-in for the OpenShell CLI."""

    def __init__(self, existing: List[str] | None = None) -> None:
        self.sandboxes: Dict[str, str] = {n: "" for n in existing or []}
        self.created: List[str] = []
        self.deleted: List[str] = []

    def create(self, name: str, policy: str) -> None:
        assert name not in self.sandboxes
        self.sandboxes[name] = policy
        self.created.append(name)

    def delete(self, name: str) -> None:
        self.sandboxes.pop(name, None)
        self.deleted.append(name)

    def list_names(self) -> List[str]:
        return list(self.sandboxes)


POLICY_A = '{"network_policies": {}}'
POLICY_B = '{"network_policies": {"openjarvis": {}}}'


@pytest.fixture
def shell() -> FakeOpenShell:
    return FakeOpenShell()


@pytest.fixture
def pool(shell: FakeOpenShell) -> SandboxPool:
    return SandboxPool(shell, image_id="sha256:aaa")


class TestClaim:
    def test_claim_without_warm_sandbox_creates_one_with_the_policy(self, pool, shell):
        sandbox = pool.claim("digest", POLICY_A)
        assert shell.sandboxes[sandbox.name] == POLICY_A

    def test_claim_uses_a_warm_sandbox_without_creating(self, pool, shell):
        pool.set_size("chat", POLICY_A, 1)
        warm = list(shell.sandboxes)
        sandbox = pool.claim("chat", POLICY_A)
        assert sandbox.name in warm

    def test_claim_refills_to_the_agent_pool_size(self, pool, shell):
        pool.set_size("chat", POLICY_A, 1)
        claimed = pool.claim("chat", POLICY_A)
        pool.wait_for_refills()
        others = [n for n in shell.sandboxes if n != claimed.name]
        assert len(others) == 1

    def test_a_changed_policy_never_gets_an_old_sandbox(self, pool, shell):
        pool.set_size("chat", POLICY_A, 1)
        sandbox = pool.claim("chat", POLICY_B)
        assert shell.sandboxes[sandbox.name] == POLICY_B

    def test_sandbox_names_carry_the_prefix_and_are_unique(self, pool):
        names = {pool.claim("digest", POLICY_A).name for _ in range(5)}
        assert len(names) == 5
        assert all(n.startswith(f"oj-{os.getpid()}-digest-") for n in names)

    def test_agent_ids_are_made_safe_for_sandbox_names(self, pool):
        name = pool.claim("Morning_Digest", POLICY_A).name
        assert name.startswith(f"oj-{os.getpid()}-morning-digest-")


class TestBackgroundRefill:
    def test_claim_does_not_wait_for_the_refill(self):
        shell = FakeOpenShell()
        pool = SandboxPool(shell, image_id="sha256:aaa")
        pool.set_size("chat", POLICY_A, 1)

        gate = threading.Event()
        original = shell.create

        def slow_create(name, policy):
            gate.wait(5)
            original(name, policy)

        shell.create = slow_create
        started = time.monotonic()
        pool.claim("chat", POLICY_A)
        elapsed = time.monotonic() - started
        gate.set()
        pool.wait_for_refills()
        assert elapsed < 1
        assert len(shell.sandboxes) == 2


class TestRelease:
    def test_release_deletes_the_sandbox(self, pool, shell):
        sandbox = pool.claim("digest", POLICY_A)
        pool.release(sandbox)
        assert sandbox.name not in shell.sandboxes

    def test_a_sandbox_is_never_handed_out_twice(self, pool):
        pool.set_size("chat", POLICY_A, 1)
        first = pool.claim("chat", POLICY_A)
        pool.release(first)
        second = pool.claim("chat", POLICY_A)
        assert second.name != first.name


class TestLifecycle:
    def test_cleanup_removes_only_prefixed_sandboxes(self):
        shell = FakeOpenShell(existing=["oj-chat-old1", "someone-else"])
        SandboxPool(shell, image_id="sha256:aaa").cleanup_orphans()
        assert list(shell.sandboxes) == ["someone-else"]

    def test_cleanup_keeps_sandboxes_of_other_running_processes(self):
        shell = FakeOpenShell(
            existing=["oj-100-chat-a", "oj-200-chat-b", "oj-300-chat-c"]
        )
        pool = SandboxPool(
            shell, image_id="sha256:aaa", pid=100, is_alive=lambda pid: pid == 200
        )
        pool.cleanup_orphans()
        assert list(shell.sandboxes) == ["oj-200-chat-b"]

    def test_drain_deletes_all_warm_sandboxes(self, pool, shell):
        pool.set_size("chat", POLICY_A, 2)
        pool.drain()
        assert shell.sandboxes == {}

    def test_size_zero_keeps_nothing_warm(self, pool, shell):
        pool.set_size("digest", POLICY_A, 0)
        assert shell.sandboxes == {}


class TestKey:
    def test_key_changes_with_policy(self, pool):
        assert pool.key(POLICY_A) != pool.key(POLICY_B)

    def test_key_changes_with_image(self, shell):
        a = SandboxPool(shell, image_id="sha256:aaa").key(POLICY_A)
        b = SandboxPool(shell, image_id="sha256:bbb").key(POLICY_A)
        assert a != b
