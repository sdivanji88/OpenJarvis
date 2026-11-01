"""Pool of pre-created OpenShell sandboxes, keyed by policy and image.

A sandbox's credentials and policy are fixed at creation, and changing a
policy on a live sandbox takes seconds, so warm sandboxes are only handed
to runs whose policy and image match exactly. Every sandbox runs a single
agent loop and is deleted afterwards.
"""

from __future__ import annotations

import hashlib
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Dict, List, Protocol, Tuple

PREFIX = "oj-"


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


class SandboxPool:
    def __init__(self, shell: OpenShell, *, image_id: str) -> None:
        self._shell = shell
        self._image_id = image_id
        self._lock = threading.Lock()
        self._warm: Dict[Tuple[str, str], List[Sandbox]] = {}
        self._sizes: Dict[Tuple[str, str], int] = {}
        self._policies: Dict[str, str] = {}

    def key(self, policy: str) -> str:
        digest = hashlib.sha256(f"{self._image_id}\n{policy}".encode())
        return digest.hexdigest()[:16]

    def set_size(self, agent: str, policy: str, size: int) -> None:
        """Keep ``size`` sandboxes warm for ``agent`` running under ``policy``."""
        slot = (agent, self.key(policy))
        self._policies[slot[1]] = policy
        self._sizes[slot] = size
        self._refill(slot)

    def claim(self, agent: str, policy: str) -> Sandbox:
        slot = (agent, self.key(policy))
        self._policies[slot[1]] = policy
        with self._lock:
            warm = self._warm.get(slot)
            sandbox = warm.pop(0) if warm else None
        if sandbox is None:
            sandbox = self._create(slot)
        self._refill(slot)
        return sandbox

    def release(self, sandbox: Sandbox) -> None:
        self._shell.delete(sandbox.name)

    def drain(self) -> None:
        with self._lock:
            warm = [s for group in self._warm.values() for s in group]
            self._warm.clear()
        for sandbox in warm:
            self._shell.delete(sandbox.name)

    def cleanup_orphans(self) -> None:
        for name in self._shell.list_names():
            if name.startswith(PREFIX):
                self._shell.delete(name)

    def _create(self, slot: Tuple[str, str]) -> Sandbox:
        agent, key = slot
        name = f"{PREFIX}{_slug(agent)}-{uuid.uuid4().hex[:8]}"
        self._shell.create(name, self._policies[key])
        return Sandbox(name=name, agent=agent, key=key)

    def _refill(self, slot: Tuple[str, str]) -> None:
        target = self._sizes.get(slot, 0)
        while len(self._warm.get(slot, [])) < target:
            sandbox = self._create(slot)
            with self._lock:
                self._warm.setdefault(slot, []).append(sandbox)


__all__ = ["OpenShell", "PREFIX", "Sandbox", "SandboxPool"]
