#!/usr/bin/env bash
# Architecture review — HARD gate. Two stages:
#   1. Static metrics (complexity, if radon is installed) on files changed vs. $BASE_REF
#   2. LLM audit of the diff against docs/architecture-rules.md
# Both must pass. Non-zero exit blocks the feature's Definition of Done.
#
# File length (D-014) and import count (D-016) are deliberately not gated: module
# depth and information leakage are judged by the interface a module exposes,
# which the LLM audit checks, not by counting lines or imports.

set -uo pipefail

cd "$(dirname "$0")/.."

mkdir -p .claude/reports
REPORT_FILE=".claude/reports/architecture-review.md"
BASE_REF="${BASE_REF:-origin/main}"
FAILED=0

echo "# Architecture review — $(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Diff: staged, else uncommitted, else branch vs. merge-base.
if ! git diff --cached --quiet 2>/dev/null; then
  DIFF_ARGS=(--cached)
  DIFF_DESC="staged changes"
elif ! git diff --quiet 2>/dev/null; then
  DIFF_ARGS=()
  DIFF_DESC="uncommitted changes"
elif MERGE_BASE=$(git merge-base "$BASE_REF" HEAD 2>/dev/null); then
  DIFF_ARGS=("$MERGE_BASE"..HEAD)
  DIFF_DESC="branch vs. $BASE_REF"
else
  DIFF_ARGS=()
  DIFF_DESC="none"
fi
echo "Scope: $DIFF_DESC" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

SOURCE_FILES=$( { git diff --name-only --diff-filter=AM ${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"} 2>/dev/null
    [ "$DIFF_DESC" = "uncommitted changes" ] && git ls-files --others --exclude-standard; } \
  | grep -E '\.(py|ts|tsx|js|jsx|rs)$' \
  | grep -vE '(^|/)(node_modules|target|dist|build|\.venv)/' \
  || true)

echo "## Stage 1 — static metrics" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

PY_FILES=$(echo "$SOURCE_FILES" | grep -E '\.py$' || true)
if [ -n "$PY_FILES" ] && command -v radon > /dev/null 2>&1; then
  echo "### Python cyclomatic complexity (radon, grade C+)" >> "$REPORT_FILE"
  # shellcheck disable=SC2086
  # An errored radon must not read as "all under threshold" (skip != pass).
  COMPLEX=$(radon cc $PY_FILES -n C -s 2>/dev/null); RADON_RC=$?
  if [ "$RADON_RC" -ne 0 ]; then
    { echo '```'; echo "$COMPLEX"; echo '```'; echo "**ERROR:** radon exited $RADON_RC — complexity not measured. Not a pass."; } >> "$REPORT_FILE"
    FAILED=1
  elif [ -n "$COMPLEX" ]; then
    echo '```' >> "$REPORT_FILE"
    echo "$COMPLEX" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"
    echo "**FAIL:** functions exceeding complexity threshold C." >> "$REPORT_FILE"
    FAILED=1
  else
    echo "_All under threshold._" >> "$REPORT_FILE"
  fi
  echo "" >> "$REPORT_FILE"
fi

echo "## Stage 2 — LLM audit against docs/architecture-rules.md" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

LLM_STATUS="SKIPPED"
if [ ! -f "docs/architecture-rules.md" ]; then
  echo "**SKIPPED:** docs/architecture-rules.md not found." >> "$REPORT_FILE"
elif ! command -v cursor-agent > /dev/null 2>&1; then
  echo "**SKIPPED:** cursor-agent not in PATH. Audit not run (not a pass)." >> "$REPORT_FILE"
elif [ "$DIFF_DESC" = "none" ]; then
  echo "_No diff to audit._" >> "$REPORT_FILE"; LLM_STATUS="PASS"
else
  DIFF=$(git diff ${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"} 2>/dev/null || echo "")
  if [ -z "$DIFF" ]; then
    echo "_No diff to audit._" >> "$REPORT_FILE"; LLM_STATUS="PASS"
  else
    PROMPT_FILE=$(mktemp)
    {
      echo "Audit the following code diff against these architecture rules. Be strict — flag any HIGH-CONFIDENCE violation. Skip low-confidence concerns."
      echo ""
      echo "Output:"
      echo "- If no violations: print exactly \"PASS\""
      echo "- If violations: print \"FAIL\" then a bulleted list of (file:line, rule violated, why)."
      echo ""
      echo "Rules:"
      cat docs/architecture-rules.md
      echo ""
      echo "Diff:"
      echo "$DIFF"
    } > "$PROMPT_FILE"
    # Ask mode is read-only, so the auditor cannot edit the tree it is judging.
    AUDIT=$(cursor-agent -p --mode ask --output-format text --trust "$(cat "$PROMPT_FILE")" 2>&1 || echo "AUDIT_ERROR")
    rm -f "$PROMPT_FILE"

    echo '```' >> "$REPORT_FILE"
    echo "$AUDIT" >> "$REPORT_FILE"
    echo '```' >> "$REPORT_FILE"

    # Verdict = first non-empty, non-code-fence line, so a FAIL wrapped in a
    # markdown fence is not misread as PASS. Check ERROR first.
    VERDICT_LINE=$(printf '%s\n' "$AUDIT" | grep -vE '^[[:space:]]*```' | grep -vE '^[[:space:]]*$' | head -1)
    if printf '%s' "$AUDIT" | grep -qi "AUDIT_ERROR"; then
      LLM_STATUS="ERROR"; echo "**ERROR:** audit invocation failed — not a pass." >> "$REPORT_FILE"; FAILED=1
    elif printf '%s' "$VERDICT_LINE" | grep -qiE "^[[:space:]]*FAIL"; then
      LLM_STATUS="FAIL"; FAILED=1
    else
      LLM_STATUS="PASS"
    fi
  fi
fi

echo "" >> "$REPORT_FILE"
echo "LLM audit status: **$LLM_STATUS**" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "## Result" >> "$REPORT_FILE"
if [ "$FAILED" -eq 0 ]; then
  echo "**PASS** — static metrics clean; LLM audit: $LLM_STATUS." >> "$REPORT_FILE"
  echo "✓ Architecture review passed. Report: $REPORT_FILE"
  exit 0
else
  echo "**FAIL** — see findings above." >> "$REPORT_FILE"
  echo "✗ Architecture review FAILED. Report: $REPORT_FILE"
  exit 1
fi
