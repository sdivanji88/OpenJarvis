#!/usr/bin/env bash
# Validate the harness itself — HARD gate. Checks that the generated harness is
# internally consistent: JSON parses and matches the feature schema, required
# files exist, agent files carry frontmatter, scripts are executable, and NO
# executable file contains an unresolved {{...}} placeholder.
# Non-zero exit means the harness is malformed.

set -uo pipefail

cd "$(dirname "$0")/.."

FAILED=0
fail() { echo "✗ $1"; FAILED=1; }
ok()   { echo "✓ $1"; }

# --- 1. Required files present ---
REQUIRED=(
  "CLAUDE.md" "feature_list.json" "session-handoff.md" "claude-progress.md"
  "clean-state-checklist.md" ".claude/harness-manifest.json"
  ".claude/skills/design-consensus/SKILL.md" ".claude/skills/wait-what/SKILL.md"
  "docs/DECISION_LOG.md"
  "scripts/test.sh" "scripts/lint.sh" "scripts/smoke.sh" "scripts/security.sh"
)
for f in "${REQUIRED[@]}"; do
  [ -e "$f" ] && ok "present: $f" || fail "missing required file: $f"
done

# --- 2. JSON parses + feature schema (v2) ---
if command -v python3 > /dev/null 2>&1; then
  python3 - <<'PY' || FAILED=1
import json, re, sys
try:
    decision_log = open("docs/DECISION_LOG.md", encoding="utf-8").read()
except OSError:
    decision_log = None
ALLOWED_FEATURE = {"todo","in_progress","implemented","verifying","verified","blocked","deferred"}
ALLOWED_AC = {"pending","pass","fail","blocked"}
ALLOWED_DESIGN = {"pending","agreed"}
ALLOWED_RISK = {"light","escalated"}
ok = True
def err(m):
    global ok; ok = False; print(f"✗ {m}")

for path in ("feature_list.json", ".claude/harness-manifest.json"):
    try:
        with open(path) as fh: json.load(fh)
        print(f"✓ valid JSON: {path}")
    except Exception as e:
        err(f"invalid JSON in {path}: {e}")

try:
    data = json.load(open("feature_list.json"))
except Exception:
    sys.exit(0 if ok else 1)

if data.get("schema_version") != 2:
    err("feature_list.json: schema_version must be 2")
for feat in data.get("features", []):
    fid = feat.get("id","<no-id>")
    if feat.get("status") not in ALLOWED_FEATURE:
        err(f"feature {fid}: invalid status {feat.get('status')!r}")
    design = feat.get("design")
    if design is not None:
        if design.get("status") not in ALLOWED_DESIGN:
            err(f"feature {fid}: invalid design.status {design.get('status')!r}")
        if design.get("risk") not in ALLOWED_RISK:
            err(f"feature {fid}: invalid design.risk {design.get('risk')!r}")
        refs = design.get("decision_refs", [])
        if not isinstance(refs, list) or any(not re.fullmatch(r"D-\d{3,}", str(r)) for r in refs):
            err(f"feature {fid}: design.decision_refs must be a list of D-NNN ids, got {refs!r}")
        for r in refs if isinstance(refs, list) else []:
            if decision_log is not None and not re.search(rf"^## {re.escape(str(r))}\b", decision_log, re.M):
                err(f"feature {fid}: design.decision_refs cites {r} but docs/DECISION_LOG.md has no such entry")
    for ac in feat.get("acceptance_criteria", []):
        st = ac.get("status")
        if st not in ALLOWED_AC:
            err(f"feature {fid}/{ac.get('id')}: invalid acceptance status {st!r}")
        # An acceptance criterion may be 'pass' only with matching evidence.
        if st == "pass":
            ev = ac.get("evidence", [])
            good = any(
                (e.get("type")=="command" and e.get("exit_code")==0) or
                (e.get("type")=="manual" and e.get("observed"))
                for e in ev
            )
            if not good:
                err(f"feature {fid}/{ac.get('id')}: status 'pass' without matching evidence")
print("✓ feature schema checks complete" if ok else "✗ feature schema checks failed")
sys.exit(0 if ok else 1)
PY
else
  fail "python3 not found — cannot validate JSON/schema (BLOCKED, not a pass)"
fi

# --- 3. Agent and skill files carry YAML frontmatter ---
while IFS= read -r -d '' af; do
  if head -1 "$af" | grep -q '^---$'; then ok "frontmatter: $af"; else fail "missing frontmatter: $af"; fi
done < <(find .claude/agents -name '*.md' -print0 2>/dev/null; \
         find .claude/skills -name 'SKILL.md' -print0 2>/dev/null)

# --- 4. Scripts are executable ---
while IFS= read -r -d '' s; do
  [ -x "$s" ] && ok "executable: $s" || fail "not executable (chmod +x): $s"
done < <(find scripts -name '*.sh' -print0 2>/dev/null)

# --- 5. No unresolved template placeholders in executable files ---
# A placeholder is two opening braces followed by a letter. The pattern is
# written with escaped braces so this check does not flag its own source line.
while IFS= read -r -d '' ex; do
  if grep -qE '\{\{[A-Za-z]' "$ex"; then
    fail "unresolved placeholder in executable file: $ex"
  fi
done < <(find scripts -name '*.sh' -print0 2>/dev/null; \
         find . -maxdepth 2 -name 'feature_list.json' -print0 2>/dev/null; \
         find .claude -name 'harness-manifest.json' -print0 2>/dev/null)

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "✓ Harness validation passed"
  exit 0
else
  echo "✗ Harness validation FAILED"
  exit 1
fi
