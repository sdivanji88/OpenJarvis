"""Agent entrypoint that runs inside a sandbox.

Reads one JSON request on stdin, runs the requested agent, and prints its
result between the output sentinels. Models are reached only through the
OpenShell inference gateway; failures exit non-zero with the reason on
stderr so the host reports them instead of retrying on the host.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional, TextIO

from openjarvis.engine._stubs import InferenceEngine

OUTPUT_START = "---OPENJARVIS_OUTPUT_START---"
OUTPUT_END = "---OPENJARVIS_OUTPUT_END---"
DEFAULT_INFERENCE_URL = "https://inference.local"


class _RequestError(ValueError):
    pass


def _parse(raw: str) -> Dict[str, Any]:
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _RequestError(f"Invalid request JSON: {exc}") from exc
    if not isinstance(request, dict):
        raise _RequestError("Invalid request: expected a JSON object")
    for field in ("prompt", "agent_id"):
        if not request.get(field):
            raise _RequestError(f"Invalid request: missing {field}")
    return request


def _gateway_engine() -> InferenceEngine:
    from openjarvis.engine.openai_compat_engines import VLLMEngine

    return VLLMEngine(
        host=os.environ.get("OPENJARVIS_INFERENCE_URL", DEFAULT_INFERENCE_URL)
    )


def _run(request: Dict[str, Any], engine: InferenceEngine) -> Dict[str, Any]:
    import openjarvis.agents  # noqa: F401  (registers agents)
    from openjarvis.agents.factory import build_agent
    from openjarvis.core.config import JarvisConfig
    from openjarvis.core.registry import AgentRegistry

    agent_id = request["agent_id"]
    if not AgentRegistry.contains(agent_id):
        raise _RequestError(f"Unknown agent: {agent_id}")
    workspace = request.get("_workspace")
    if workspace:
        os.chdir(workspace)

    agent = build_agent(
        AgentRegistry.get(agent_id),
        engine,
        request.get("model", ""),
        config=JarvisConfig(),
    )
    result = agent.run(request["prompt"])
    return {
        "content": result.content,
        "tool_results": [
            {"tool_name": tr.tool_name, "content": tr.content, "success": tr.success}
            for tr in result.tool_results
        ],
        "metadata": result.metadata,
    }


def main(
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    engine: Optional[InferenceEngine] = None,
) -> int:
    try:
        request = _parse(stdin.read())
        output = _run(request, engine or _gateway_engine())
    except _RequestError as exc:
        print(str(exc), file=stderr)
        return 2
    except Exception as exc:
        print(f"Agent failed: {type(exc).__name__}: {exc}", file=stderr)
        return 1
    stdout.write(f"{OUTPUT_START}\n{json.dumps(output, default=str)}\n{OUTPUT_END}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
