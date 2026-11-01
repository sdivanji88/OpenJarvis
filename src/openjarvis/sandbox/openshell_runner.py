"""Runs agent loops in single-use OpenShell sandboxes.

Drop-in alternative to :class:`ContainerRunner` for ``SandboxedAgent``.
Every failure is reported as an error result: an agent never falls back
to running on the host.
"""

from __future__ import annotations

import atexit
import json
import logging
import re
import shlex
import subprocess
import threading
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
)

from openjarvis.core.config import SandboxConfig
from openjarvis.sandbox.openshell_cli import (
    OpenShellCLI,
    OpenShellError,
    SandboxTimeout,
)
from openjarvis.sandbox.openshell_policy import build_policy, render_policy
from openjarvis.sandbox.openshell_pool import OpenShell, SandboxPool
from openjarvis.sandbox.runner import ContainerRunner

logger = logging.getLogger(__name__)

DEFAULT_COMMAND = "/sandbox/.venv/bin/python -m openjarvis.sandbox.entrypoint"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class OpenShellRuntime(OpenShell, Protocol):
    def exec(
        self, name: str, command: str, *, input: str, timeout: float
    ) -> subprocess.CompletedProcess: ...

    def gateway_ready(self) -> bool: ...


def _error(content: str, error_type: str) -> Dict[str, Any]:
    return {"content": content, "error": True, "error_type": error_type}


class OpenShellRunner:
    def __init__(
        self,
        shell: OpenShellRuntime,
        *,
        image_id: str,
        allowed_hosts: Optional[Mapping[str, Sequence[str]]] = None,
        pool_sizes: Optional[Mapping[str, int]] = None,
        timeout: float = 300,
        command: str = DEFAULT_COMMAND,
    ) -> None:
        self._shell = shell
        self._pool = SandboxPool(shell, image_id=image_id)
        self._allowed_hosts = dict(allowed_hosts or {})
        self._pool_sizes = dict(pool_sizes or {})
        self._timeout = timeout
        self._command = command

    def policy_for(self, agent: str) -> str:
        return render_policy(build_policy(self._allowed_hosts.get(agent, [])))

    def start(self) -> None:
        """Remove sandboxes left by a previous process and warm the pools."""
        if not self._shell.gateway_ready():
            raise OpenShellError("OpenShell gateway is not connected")
        self._pool.cleanup_orphans()
        for agent, size in self._pool_sizes.items():
            self._pool.set_size(agent, self.policy_for(agent), size)

    def shutdown(self) -> None:
        self._pool.drain()
        try:
            self._pool.cleanup_orphans()
        except OpenShellError:
            logger.warning("Sandbox cleanup at shutdown failed", exc_info=True)

    close = shutdown

    def run(
        self,
        input_data: Dict[str, Any],
        *,
        workspace: str = "",
        mounts: Optional[List[str]] = None,
        secrets: Optional[Dict[str, str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        if mounts:
            return _error(
                "The OpenShell runtime does not mount host folders.", "refused"
            )
        if secrets:
            return _error(
                "The OpenShell runtime does not pass secrets into sandboxes; "
                "personal data is reached through host-side connectors.",
                "refused",
            )

        bad_names = [k for k in env or {} if not _ENV_NAME.match(k)]
        if bad_names:
            return _error(f"Invalid environment variable names: {bad_names}", "refused")

        payload = dict(input_data)
        if workspace:
            payload["_workspace"] = workspace
        agent = str(input_data.get("agent_id", ""))

        try:
            sandbox = self._pool.claim(agent, self.policy_for(agent))
        except OpenShellError as exc:
            return _error(f"No sandbox available: {exc}", "sandbox_unavailable")

        try:
            proc = self._shell.exec(
                sandbox.name,
                self._build_command(env),
                input=json.dumps(payload),
                timeout=self._timeout,
            )
        except SandboxTimeout:
            return _error(f"Sandbox timed out after {self._timeout}s.", "timeout")
        except OpenShellError as exc:
            return _error(f"Sandbox failed: {exc}", "sandbox_unavailable")
        finally:
            self._pool.release(sandbox)

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            logger.error(
                "Sandbox %s exited %d: %s", sandbox.name, proc.returncode, stderr
            )
            return {
                "content": f"Sandbox failed: {stderr}",
                "error": True,
                "returncode": proc.returncode,
            }
        return ContainerRunner._parse_output(proc.stdout)

    def _build_command(self, env: Optional[Dict[str, str]]) -> str:
        if not env:
            return self._command
        assignments = " ".join(f"{k}={shlex.quote(v)}" for k, v in env.items())
        return f"env {assignments} {self._command}"


_shared: Dict[Tuple[str, ...], OpenShellRunner] = {}
_shared_lock = threading.Lock()


def shared_runner(
    sandbox: SandboxConfig,
    *,
    shell_factory: Optional[Callable[[str], OpenShellRuntime]] = None,
) -> Optional[OpenShellRunner]:
    """Return the process-wide runner for ``sandbox``, or None if not OpenShell.

    The runner is started once (orphan cleanup, warm pools) and shut down at
    exit. If OpenShell is unavailable the runner is still returned, so agent
    runs are refused instead of silently running on the host.
    """
    if sandbox.runtime != "openshell":
        return None
    key = (
        sandbox.image,
        str(sandbox.timeout),
        json.dumps(sandbox.allowed_hosts, sort_keys=True),
        json.dumps(sandbox.pool_sizes, sort_keys=True),
    )
    with _shared_lock:
        runner = _shared.get(key)
        if runner is not None:
            return runner
        make_shell = shell_factory or (lambda image: OpenShellCLI(image=image))
        runner = OpenShellRunner(
            make_shell(sandbox.image),
            image_id=sandbox.image,
            allowed_hosts=sandbox.allowed_hosts,
            pool_sizes=sandbox.pool_sizes,
            timeout=sandbox.timeout,
        )
        try:
            runner.start()
        except OpenShellError as exc:
            logger.error(
                "OpenShell sandbox runtime unavailable; agent runs will be refused: %s",
                exc,
            )
        atexit.register(runner.shutdown)
        _shared[key] = runner
        return runner


def _clear_shared() -> None:
    with _shared_lock:
        _shared.clear()


shared_runner.cache_clear = _clear_shared  # type: ignore[attr-defined]


__all__ = ["DEFAULT_COMMAND", "OpenShellRunner", "OpenShellRuntime", "shared_runner"]
