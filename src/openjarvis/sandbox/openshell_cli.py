"""Adapter over the ``openshell`` CLI and SSH.

Sandboxes are created to stay alive and then driven over SSH: output from
``sandbox create -- <cmd>`` mixes in OpenShell's progress lines, whereas
SSH gives clean stdout and propagates the remote exit code.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

Run = Callable[..., subprocess.CompletedProcess]


class OpenShellError(RuntimeError):
    """An OpenShell operation failed; the run must not fall back to the host."""


class SandboxTimeout(OpenShellError):
    """An OpenShell or SSH command exceeded its timeout."""


class OpenShellCLI:
    def __init__(
        self,
        *,
        image: str,
        binary: str = "openshell",
        run: Run = subprocess.run,
        state_dir: Optional[Path] = None,
        create_timeout: float = 120.0,
    ) -> None:
        self._image = image
        self._binary = binary
        self._run = run
        # OpenShell's own provisioning timeout is 300 s, and an image that
        # cannot start is reported as Provisioning forever.
        self._create_timeout = create_timeout
        self._state_dir = state_dir
        self._ssh_configs: Dict[str, Path] = {}

    def create(self, name: str, policy: str) -> None:
        policy_file = self._write(f"{name}.policy.json", policy)
        argv = [
            self._binary, "sandbox", "create",
            "--name", name,
            "--from", self._image,
            "--no-tty", "--no-auto-providers",
            "--policy", str(policy_file),
            "--", "true",
        ]  # fmt: skip
        try:
            result = self._call(argv, timeout=self._create_timeout)
            if result.returncode != 0:
                raise OpenShellError(
                    f"creating sandbox {name} failed: {result.stderr.strip()}"
                )
            config = self._call(
                [self._binary, "sandbox", "ssh-config", name], timeout=30
            )
            if config.returncode != 0:
                raise OpenShellError(
                    f"ssh-config for {name} failed: {config.stderr.strip()}"
                )
        except OpenShellError:
            self.delete(name)
            raise
        finally:
            policy_file.unlink(missing_ok=True)
        self._ssh_configs[name] = self._write(f"{name}.ssh", config.stdout)

    def exec(
        self, name: str, command: str, *, input: str, timeout: float
    ) -> subprocess.CompletedProcess:
        config = self._ssh_configs.get(name)
        if config is None:
            raise OpenShellError(f"unknown sandbox {name}")
        argv = [
            "ssh", "-F", str(config), "-o", "BatchMode=yes",
            f"openshell-{name}", command,
        ]  # fmt: skip
        return self._call(argv, input=input, timeout=timeout)

    def delete(self, name: str) -> None:
        config = self._ssh_configs.pop(name, None)
        if config is not None:
            config.unlink(missing_ok=True)
        try:
            result = self._call([self._binary, "sandbox", "delete", name], timeout=60)
        except OpenShellError as exc:
            logger.warning("Deleting sandbox %s failed: %s", name, exc)
            return
        if result.returncode != 0:
            logger.warning(
                "Deleting sandbox %s failed: %s", name, result.stderr.strip()
            )

    def list_names(self) -> List[str]:
        result = self._call([self._binary, "sandbox", "list", "--names"], timeout=30)
        if result.returncode != 0:
            raise OpenShellError(f"listing sandboxes failed: {result.stderr.strip()}")
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def gateway_ready(self) -> bool:
        try:
            result = self._call([self._binary, "status"], timeout=15)
        except OpenShellError:
            return False
        return result.returncode == 0 and "Connected" in result.stdout

    def _call(
        self, argv: List[str], *, timeout: float, input: Optional[str] = None
    ) -> subprocess.CompletedProcess:
        try:
            return self._run(
                argv, input=input, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired as exc:
            raise SandboxTimeout(f"{' '.join(argv[:3])} timed out") from exc
        except FileNotFoundError as exc:
            raise OpenShellError(f"{argv[0]} not found on PATH") from exc

    def _write(self, filename: str, content: str) -> Path:
        if self._state_dir is None:
            self._state_dir = Path(tempfile.mkdtemp(prefix="oj-openshell-"))
        path = self._state_dir / filename
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        return path


__all__ = ["OpenShellCLI", "OpenShellError", "SandboxTimeout"]
