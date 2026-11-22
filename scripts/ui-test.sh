#!/usr/bin/env bash
# UI tests — HARD gate when frontend/ is in scope.
# Runs the frontend type-check and Vitest suite (mirrors .github/workflows/frontend.yml).

set -euo pipefail

cd "$(dirname "$0")/../frontend"

echo "Running UI tests for OpenJarvis..."

if [ ! -d node_modules ]; then
  npm ci
fi

npx tsc --noEmit
npm test

echo "✓ UI tests passed"
