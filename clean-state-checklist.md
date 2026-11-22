# Clean State Checklist — OpenJarvis

Run through this checklist before merging any non-trivial change. Each section has hard checks (must pass) and discretion checks (judge per change).

---

## 1. Build

- [ ] `uv sync --extra dev --extra framework-comparison --extra server` completes with exit 0
- [ ] `uv run maturin develop --manifest-path rust/crates/openjarvis-python/Cargo.toml` succeeds if `rust/` changed
- [ ] `(cd frontend && npm run build)` succeeds if `frontend/` changed (`tsc -b && vite build`)
- [ ] No unintended changes to `uv.lock`, `frontend/package-lock.json`, or `rust/Cargo.lock`
- [ ] Build artifacts are gitignored (no `dist/`, `target/`, `__pycache__/`, `server/static` build output in `git status`)
- [ ] New optional dependencies go in a `pyproject.toml` extra, not core `dependencies`

## 2. Architecture

- [ ] `scripts/architecture-review.sh` passes (hard gate)
- [ ] No module added with a shallow interface (interface complexity ≈ implementation complexity)
- [ ] No information leak introduced (a single change should not require edits in unrelated modules)
- [ ] New errors are defined out of existence where possible, not thrown
- [ ] New engines/agents/tools/channels register through `core/registry.py` and emit via `EventBus`
- [ ] If a subsystem has a Rust mirror in `rust/crates/`, Python and Rust behavior stay consistent (or divergence is documented)
- [ ] `docs/ARCHITECTURE.md` / `docs/architecture/*.md` updated if module boundaries changed

## 3. Runtime

- [ ] `uv run jarvis doctor` reports no new failures
- [ ] `scripts/smoke.sh` passes (`jarvis --version` + `jarvis doctor` through the real CLI)
- [ ] With a local engine: `uv run jarvis ask "hello"` or `uv run jarvis digest --text-only` returns output
- [ ] `uv run jarvis serve` starts and `GET /health` returns 200
- [ ] No errors or unexpected warnings in startup logs
- [ ] Server still refuses non-loopback binds without `OPENJARVIS_API_KEY`

## 4. Logging

- [ ] Modules use `logger = logging.getLogger(__name__)` — no `print()` in library paths (CLI output goes through Rich)
- [ ] No `console.log()` left in `frontend/src/` production paths
- [ ] Errors logged with exception info + context, not bare messages
- [ ] Inference calls still record telemetry (latency, TTFT, energy) — don't bypass the telemetry wrapper
- [ ] No secrets, tokens, or personal data (emails, health data) written to logs or traces

## 5. Data integrity

- [ ] SQLite schema changes (telemetry, traces, sessions, audit, digests) are backward-compatible with existing `OPENJARVIS_HOME` databases, or a migration is provided
- [ ] Persistence tests cover round-trip serialize/deserialize
- [ ] Config changes keep existing TOML configs in `configs/` loading
- [ ] Reset / clean-slate path works (fresh `OPENJARVIS_HOME`)
- [ ] Connector syncs are idempotent (re-running doesn't duplicate records)

## 6. Performance

- [ ] Baselines in `docs/RELIABILITY.md` not regressed (TTFT, tokens/s, startup)
- [ ] No obvious N+1 queries or unbounded loops introduced
- [ ] Memory footprint stable under repeated operations
- [ ] Heavy imports (torch, vllm, mlx, faiss) stay lazy — `jarvis --help` stays fast
- [ ] If benchmarks were run, results recorded in `session-handoff.md`

## 7. Security

- [ ] `scripts/security.sh` ran — result is PASS (a BLOCKED result for missing tooling such as `gitleaks` is not a pass)
- [ ] New tools, connectors, and channels go through `security/` guardrails and the audit log; untrusted model or tool output never reaches a shell or the sandbox unchecked
- [ ] Server routes keep the loopback-or-`OPENJARVIS_API_KEY` rule; no new unauthenticated non-loopback surface
- [ ] Dependency changes are locked in `uv.lock` / `package-lock.json` / `Cargo.lock`; no known high-severity advisories left unaddressed

## 8. Repository

- [ ] No secrets committed (scan for keys, tokens, `.env` files)
- [ ] `.gitignore` covers all generated files
- [ ] No commented-out blocks of code left in
- [ ] No `TODO:` / `FIXME:` left without a tracking issue reference
- [ ] `feature_list.json` is up to date — every feature mentioned in CLAUDE.md appears with a `status`
- [ ] `session-handoff.md` is current
- [ ] `CHANGELOG.md` updated for user-facing changes

## 9. Scripts

- [ ] All `scripts/*.sh` harness gates are executable (`chmod +x`)
- [ ] `scripts/validate-harness.sh` exits 0 (harness internally consistent, no unresolved placeholders)
- [ ] `scripts/lint.sh` runs and reports cleanly (warnings allowed, errors must be addressed)
- [ ] `scripts/test.sh` exits 0
- [ ] `scripts/integration.sh` exits 0
- [ ] `scripts/smoke.sh` exits 0
- [ ] `scripts/security.sh` exits 0 (PASS, not BLOCKED)
- [ ] `scripts/ui-test.sh` exits 0 if `frontend/` changed
- [ ] `scripts/architecture-review.sh` exits 0
- [ ] `scripts/code-review.sh` produced a report at `.claude/reports/code-review.md` and it was reviewed
- [ ] Rust changed → `cargo clippy --workspace --all-targets -- -D warnings && cargo test --workspace` pass

---

## How to use this checklist

Walk through every item. The point of this file is to **encode tribal knowledge** about what "done" means here — add checks when a regression slips through.
