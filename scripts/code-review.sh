#!/usr/bin/env bash
# Code review — SOFT gate. Writes a markdown report to .claude/reports/code-review.md.
# Always exits 0; humans/agents are expected to read the report.

set -uo pipefail

cd "$(dirname "$0")/.."

mkdir -p .claude/reports
REPORT_FILE=".claude/reports/code-review.md"
BASE_REF="${BASE_REF:-origin/main}"

if ! git rev-parse --git-dir > /dev/null 2>&1; then
  echo "Not a git repo — skipping code review."
  exit 0
fi

# Diff range: staged changes, else uncommitted changes, else branch vs. merge-base with $BASE_REF.
if ! git diff --cached --quiet 2>/dev/null; then
  DIFF_CONTENT=$(git diff --cached)
  DIFF_DESC="staged changes"
elif ! git diff --quiet 2>/dev/null; then
  DIFF_CONTENT=$(git diff)
  DIFF_DESC="uncommitted changes"
elif MERGE_BASE=$(git merge-base "$BASE_REF" HEAD 2>/dev/null); then
  DIFF_CONTENT=$(git diff "$MERGE_BASE"..HEAD)
  DIFF_DESC="branch vs. $BASE_REF"
else
  echo "No diff base found — skipping code review."
  exit 0
fi

echo "Running code review on $DIFF_DESC..."

if [ -z "$DIFF_CONTENT" ]; then
  echo "Empty diff — skipping."
  exit 0
fi

if command -v cursor-agent > /dev/null 2>&1; then
  PROMPT_FILE=$(mktemp)
  cat > "$PROMPT_FILE" <<'EOF'
You are reviewing a code diff for OpenJarvis for correctness, clarity, and adherence to the architecture rules in docs/architecture-rules.md and the conventions in REVIEW.md.

Output a markdown report with these sections:

## Summary
One-paragraph overall assessment.

## Findings
For each finding: severity (high/medium/low), file:line, what's wrong, suggested fix.

## Architecture rule violations
Specifically flag violations of: deep modules, information hiding, defining errors out of existence, pulling complexity downward, naming/commenting. Also flag new components that bypass core/registry.py or the EventBus.

Only flag things you are confident about. Empty sections are fine.

The diff:
EOF
  echo "$DIFF_CONTENT" >> "$PROMPT_FILE"

  # Ask mode is read-only, so the reviewer cannot edit the tree it is judging.
  cursor-agent -p --mode ask --output-format text --trust "$(cat "$PROMPT_FILE")" > "$REPORT_FILE" 2>&1 || {
    echo "⚠ cursor-agent -p failed; writing placeholder report."
    echo "# Code review (placeholder)" > "$REPORT_FILE"
    echo "cursor-agent invocation failed. Run \`cursor-agent\` manually against the $DIFF_DESC diff." >> "$REPORT_FILE"
  }
  rm -f "$PROMPT_FILE"
else
  echo "# Code review (placeholder)" > "$REPORT_FILE"
  echo "cursor-agent not found in PATH — install the Cursor CLI to enable LLM-driven code review." >> "$REPORT_FILE"
fi

echo "✓ Code review report written to $REPORT_FILE (soft gate — not blocking)"
exit 0
