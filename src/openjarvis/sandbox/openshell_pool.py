"""Pool of pre-created OpenShell sandboxes, keyed by policy and image.

A sandbox's credentials and policy are fixed at creation, and changing a
policy on a live sandbox takes seconds, so warm sandboxes are only handed
to runs whose policy and image match exactly. Every sandbox runs a single
agent loop and is deleted afterwards.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol, Tuple

logger = logging.getLogger(__name__)

PREFIX = "oj-"

Slot = Tuple[str, str]


class OpenShell(Protocol):
    def create(self, name: str, policy: str) -> None: ...

    def delete(self, name: str) -> None: ...

    def list_names(self) -> List[str]: ...


@dataclass(frozen=True)
class Sandbox:
    name: str
    agent: str
    key: str


def _slug(agent: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", agent.lower()).strip("-") or "agent"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


_OWNER_RE = re.compile(rf"^{PREFIX}(\d+)-")


class SandboxPool:
    """Sandbox names are ``oj-<owner pid>-<agent>-<random>``.

    Several OpenJarvis processes (server, scheduler, CLI) share one gateway,
    so orphan cleanup only removes sandboxes whose owning process is gone.
    """

    def __init__(
        self,
        shell: OpenShell,
        *,
        image_id: str,
        pid: Optional[int] = None,
        is_alive: Callable[[int], bool] = _pid_alive,
    ) -> None:
        self._shell = shell
        self._image_id = image_id
        self._pid = os.getpid() if pid is None else pid
        self._is_alive = is_alive
        self._lock = threading.Lock()
        self._warm: Dict[Slot, List[Sandbox]] = {}
        self._pending: Dict[Slot, int] = {}
        self._sizes: Dict[Slot, int] = {}
        self._policies: Dict[str, str] = {}
        self._refills: List[threading.Thread] = []
        self._closed = False

    def key(self, policy: str) -> str:
        digest = hashlib.sha256(f"{self._image_id}\n{policy}".encode())
        return digest.hexdigest()[:16]

    def set_size(self, agent: str, policy: str, size: int) -> None:
        """Keep ``size`` sandboxes warm for ``agent`` running under ``policy``."""
        slot = self._slot(agent, policy)
        self._sizes[slot] = size
        self._refill(slot)

    def claim(self, agent: str, policy: str) -> Sandbox:
        slot = self._slot(agent, policy)
        with self._lock:
            warm = self._warm.get(slot)
            sandbox = warm.pop(0) if warm else None
        if sandbox is None:
            sandbox = self._create(slot)
        if self._sizes.get(slot, 0):
            self._refill_in_background(slot)
        return sandbox

    def release(self, sandbox: Sandbox) -> None:
        self._shell.delete(sandbox.name)

    def wait_for_refills(self) -> None:
        with self._lock:
            threads, self._refills = self._refills, []
        for thread in threads:
            thread.join()

    def drain(self) -> None:
        with self._lock:
            self._closed = True
        self.wait_for_refills()
        with self._lock:
            warm = [s for group in self._warm.values() for s in group]
            self._warm.clear()
        for sandbox in warm:
            self._shell.delete(sandbox.name)

    def cleanup_orphans(self) -> None:
        for name in self._shell.list_names():
            if name.startswith(PREFIX) and self._is_orphan(name):
                self._shell.delete(name)

    def _is_orphan(self, name: str) -> bool:
        match = _OWNER_RE.match(name)
        if match is None:
            return True
        owner = int(match.group(1))
        return owner == self._pid or not self._is_alive(owner)

    def _slot(self, agent: str, policy: str) -> Slot:
        key = self.key(policy)
        self._policies[key] = policy
        return (agent, key)

    def _create(self, slot: Slot) -> Sandbox:
        agent, key = slot
        name = f"{PREFIX}{self._pid}-{_slug(agent)}-{uuid.uuid4().hex[:8]}"
        self._shell.create(name, self._policies[key])
        return Sandbox(name=name, agent=agent, key=key)

    def _refill_in_background(self, slot: Slot) -> None:
        thread = threading.Thread(target=self._refill_quietly, args=(slot,))
        thread.daemon = True
        with self._lock:
            self._refills = [t for t in self._refills if t.is_alive()]
            self._refills.append(thread)
        thread.start()

    def _refill_quietly(self, slot: Slot) -> None:
        try:
            self._refill(slot)
        except Exception:
            logger.warning("Refilling sandbox pool %s failed", slot, exc_info=True)

    def _refill(self, slot: Slot) -> None:
        while True:
            with self._lock:
                have = len(self._warm.get(slot, [])) + self._pending.get(slot, 0)
                if self._closed or have >= self._sizes.get(slot, 0):
                    return
                self._pending[slot] = self._pending.get(slot, 0) + 1
            try:
                sandbox = self._create(slot)
            finally:
                with self._lock:
                    self._pending[slot] -= 1
            with self._lock:
                closed = self._closed
                if not closed:
                    self._warm.setdefault(slot, []).append(sandbox)
            if closed:
                self._shell.delete(sandbox.name)
                return


__all__ = ["OpenShell", "PREFIX", "Sandbox", "SandboxPool"]
