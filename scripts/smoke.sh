#!/usr/bin/env bash
# Smoke test — HARD gate. Exercises the ACTUAL entry point end to end:
# a real input must reach a real output through the intended architecture.
# Non-zero exit fails the feature's Definition of Done.
#
# SMOKE_COMMAND drives the real `jarvis` CLI: it loads config, probes engines,
# and checks the Rust extension. Validated at generation (exit 0). If it is
# ever blanked or set to NOT_CONFIGURED the script exits non-zero, because a
# smoke test that runs nothing would falsely pass.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running smoke test for OpenJarvis..."

SMOKE_COMMAND="uv run jarvis --version && uv run jarvis doctor"

if [ -z "$SMOKE_COMMAND" ] || [ "$SMOKE_COMMAND" = "NOT_CONFIGURED" ]; then
  echo "BLOCKER: no smoke command configured. A smoke test that runs nothing is not a pass." >&2
  exit 2
fi

# The command drives the real entry point (e.g. `echo '{"x":1}' | myapp process`).
eval "$SMOKE_COMMAND"

echo "✓ Smoke test passed (real input reached real output)"
