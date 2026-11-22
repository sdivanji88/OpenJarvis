#!/usr/bin/env bash
# Unit tests — HARD gate. Non-zero exit fails the feature's Definition of Done.

set -euo pipefail

cd "$(dirname "$0")/.."

echo "Running unit tests for OpenJarvis..."

if ! uv run python -c "import openjarvis_rust" > /dev/null 2>&1; then
  echo "Rust extension not built — running maturin develop..."
  uv run maturin develop --manifest-path rust/crates/openjarvis-python/Cargo.toml
fi

uv run pytest tests/ -n auto -q --tb=short \
  -m "not live and not cloud and not hub" \
  --ignore=tests/integration

if [ "${TEST_RUST:-0}" = "1" ]; then
  (cd rust && cargo test --workspace)
fi

echo "✓ Unit tests passed"
