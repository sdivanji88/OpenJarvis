#!/usr/bin/env bash
# Security checks — HARD gate. Orchestrates the project's native secret,
# dependency, and static-analysis checks.
#
# Honesty contract: a MISSING tool or an ERRORED audit is NON-PASSING
# (reported as BLOCKED), never silently treated as clean. Only a check that
# actually ran and found nothing counts as a pass.

set -uo pipefail

cd "$(dirname "$0")/.."

REPORT_FILE=".claude/reports/security-report.md"
mkdir -p "$(dirname "$REPORT_FILE")"
FAILED=0
BLOCKED=0

echo "# Security review — $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Record a stage outcome: name, status (PASS|FAIL|BLOCKED), detail.
record() {
  local name="$1" status="$2" detail="$3"
  echo "## $name — $status" >> "$REPORT_FILE"
  [ -n "$detail" ] && { echo '```' >> "$REPORT_FILE"; echo "$detail" >> "$REPORT_FILE"; echo '```' >> "$REPORT_FILE"; }
  echo "" >> "$REPORT_FILE"
  case "$status" in
    FAIL) FAILED=1 ;;
    BLOCKED) BLOCKED=1 ;;
  esac
}

# Run a stage: if the tool is absent, mark BLOCKED (not skipped-as-pass).
run_stage() {
  local name="$1" tool="$2"; shift 2
  if ! command -v "$tool" > /dev/null 2>&1; then
    record "$name" "BLOCKED" "required tool '$tool' not found in PATH"
    return
  fi
  local out rc
  out=$("$tool" "$@" 2>&1); rc=$?
  if [ "$rc" -eq 0 ]; then
    record "$name" "PASS" "$out"
  else
    record "$name" "FAIL" "$out"
  fi
}

# --- Project-native checks. The generator wires the ones this stack supports. ---
# SECURITY_COMMAND mirrors .github/workflows/security-sast.yml: bandit (pinned)
# over src/openjarvis, then pip-audit (pinned) against the local uv environment.
# Rendered as a single stage below.

SECURITY_COMMAND="uvx bandit==1.9.4 -r src/openjarvis -lll -iii -f screen -q && uv run --with pip-audit==2.10.1 pip-audit --skip-editable --progress-spinner off"
if [ -n "$SECURITY_COMMAND" ] && [ "$SECURITY_COMMAND" != "NOT_CONFIGURED" ]; then
  OUT=$(eval "$SECURITY_COMMAND" 2>&1); RC=$?
  if [ "$RC" -eq 0 ]; then record "Dependency/static audit" "PASS" "$OUT"; else record "Dependency/static audit" "FAIL" "$OUT"; fi
else
  record "Dependency/static audit" "BLOCKED" "no security command configured for this project"
fi

# --- Secret scan (best-effort, tool-agnostic fallback). ---
if command -v gitleaks > /dev/null 2>&1; then
  run_stage "Secret scan (gitleaks)" gitleaks detect --no-banner --redact
else
  # Fallback: crude grep for common secret patterns in tracked files. Absence of
  # a dedicated scanner is BLOCKED, but we still surface obvious leaks.
  # tests/, docs/ and eval fixtures deliberately contain fake credentials
  # (secret-scanner and redaction tests), so they are excluded from the grep.
  HITS=$(git grep -nIE '(AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|password\s*=\s*["'"'"'][^"'"'"']+)' \
    -- . ':!tests/' ':!docs/' ':!src/openjarvis/evals/' 2>/dev/null || true)
  if [ -n "$HITS" ]; then
    record "Secret scan (grep fallback)" "FAIL" "$HITS"
  else
    record "Secret scan" "BLOCKED" "no gitleaks in PATH; grep fallback found nothing but is not authoritative"
  fi
fi

echo "## Result" >> "$REPORT_FILE"
if [ "$FAILED" -ne 0 ]; then
  echo "**FAIL** — security findings above." >> "$REPORT_FILE"
  echo "✗ Security checks FAILED. Report: $REPORT_FILE"
  exit 1
elif [ "$BLOCKED" -ne 0 ]; then
  echo "**BLOCKED** — one or more required checks could not run (see above). NOT a pass." >> "$REPORT_FILE"
  echo "⚠ Security checks BLOCKED (missing tooling). Report: $REPORT_FILE"
  exit 3
else
  echo "**PASS** — all configured security checks ran clean." >> "$REPORT_FILE"
  echo "✓ Security checks passed. Report: $REPORT_FILE"
  exit 0
fi
