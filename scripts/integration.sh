#!/usr/bin/env bash
# Integration tests — HARD gate. Non-zero exit fails the feature's Definition of Done.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running integration tests for OpenJarvis..."

uv run pytest tests/integration tests/test_digest_integration.py -q --tb=short \
  -m "not live and not cloud and not hub"

echo "✓ Integration tests passed"
