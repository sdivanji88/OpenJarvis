"""Generate OpenShell sandbox policies from an agent's allowed hosts.

Every policy starts from a deny-all base: no network access, writes only
under ``/sandbox`` and ``/tmp``, processes run as the ``sandbox`` user.
Allowed hosts are added as a single network rule scoped to the binaries
that may use them. OpenShell matches the resolved executable, so the
default binaries include the image's Python behind the venv symlink
(see ``deploy/openshell/Dockerfile``).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Sequence

DEFAULT_BINARIES = (
    "/sandbox/.venv/bin/python3",
    "/usr/local/bin/python3.12",
)

_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?"
_HOST_RE = re.compile(rf"^{_LABEL}(\.{_LABEL})*$")


def _parse_host(entry: str) -> Dict[str, Any]:
    host, sep, port_str = entry.partition(":")
    port = 443
    if sep:
        if not port_str.isdigit():
            raise ValueError(f"Invalid port in allowed host {entry!r}")
        port = int(port_str)
        if not 1 <= port <= 65535:
            raise ValueError(f"Port out of range in allowed host {entry!r}")
    if not _HOST_RE.match(host):
        raise ValueError(
            f"Allowed host {entry!r} must be a plain hostname, optionally with :port"
        )
    return {"host": host, "port": port}


def build_policy(
    allowed_hosts: Sequence[str],
    *,
    binaries: Sequence[str] = DEFAULT_BINARIES,
) -> Dict[str, Any]:
    """Return an OpenShell policy allowing only ``allowed_hosts``."""
    endpoints = [_parse_host(h) for h in allowed_hosts]
    network: Dict[str, Any] = {}
    if endpoints:
        network["openjarvis"] = {
            "name": "openjarvis",
            "endpoints": endpoints,
            "binaries": [{"path": b} for b in binaries],
        }
    read_only: List[str] = ["/usr", "/lib", "/proc", "/dev/urandom", "/app", "/etc"]
    return {
        "version": 1,
        "filesystem_policy": {
            "include_workdir": True,
            "read_only": read_only,
            "read_write": ["/sandbox", "/tmp", "/dev/null"],
        },
        "landlock": {"compatibility": "best_effort"},
        "process": {"run_as_user": "sandbox", "run_as_group": "sandbox"},
        "network_policies": network,
    }


def render_policy(policy: Dict[str, Any]) -> str:
    """Serialize a policy for ``--policy``; JSON is valid YAML to OpenShell."""
    return json.dumps(policy, indent=2, sort_keys=True)


__all__ = ["DEFAULT_BINARIES", "build_policy", "render_policy"]
