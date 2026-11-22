#!/usr/bin/env bash
# Lint — SOFT gate. Reports problems but does not block.
# Exits 0 unless the lint tool itself crashes.

set -uo pipefail

cd "$(dirname "$0")/.."

mkdir -p .claude/reports
REPORT_FILE=".claude/reports/lint-report.txt"

echo "Running lint for OpenJarvis..." | tee "$REPORT_FILE"

LINT_EXIT=0

run() {
  echo "\$ $*" | tee -a "$REPORT_FILE"
  "$@" 2>&1 | tee -a "$REPORT_FILE"
  local code=${PIPESTATUS[0]}
  [ "$code" -ne 0 ] && LINT_EXIT=$code
  return 0
}

run uv run ruff check src/ tests/
run uv run ruff format --check src/ tests/

if [ -d frontend/node_modules ]; then
  run bash -c "cd frontend && npx tsc --noEmit"
fi

if [ "${LINT_RUST:-0}" = "1" ] && command -v cargo > /dev/null 2>&1; then
  run bash -c "cd rust && cargo clippy --workspace --all-targets -- -D warnings"
fi

if [ "$LINT_EXIT" -eq 0 ]; then
  echo "✓ Lint clean" | tee -a "$REPORT_FILE"
else
  echo "⚠ Lint reported issues (soft gate — not blocking). See $REPORT_FILE." | tee -a "$REPORT_FILE"
fi

# Soft gate: always exit 0
exit 0
