# Decision log — OpenJarvis

> How each design decision was arrived at, written for a teammate who was not in the conversation.
> **Append-only.** Never edit or delete a past entry. To change a decision, append a new entry that names the one it supersedes.
> The outcome also lives where it applies (`docs/PROJECT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/architecture-rules.md`, or `feature_list.json` → `design.decision_refs`); this log holds the premise behind it.

## How to write an entry

The reader is someone who was not there. Write so they never need to ask "wait, what?":

- **Lead with the premise:** the situation that forced the choice, what we knew, and which constraint mattered most.
- **Plain English, short sentences.** One idea per sentence. No acronyms or shorthand invented during the conversation.
- **Use the project's own nouns** from `docs/PROJECT_SPEC.md` and `docs/ARCHITECTURE.md`. If a new term is unavoidable, define it in the entry.
- **The test:** a teammate who reads only this entry can explain why we chose this.

Entry format:

```markdown
## D-NNN — <short title in project terms>

- **Date:** <YYYY-MM-DD>
- **Scope:** product | architecture | feature F-NNN
- **Premise:** <2-4 plain-English sentences: what forced this choice, what we knew, the constraint that mattered>
- **Decision:** <one sentence>
- **Supersedes:** <D-NNN, or "none">
- **Recorded in:** <doc section or feature ID where the outcome lives>
```

## Entries

## D-001 — Morning digest work goes through the full feature flow

- **Date:** 2026-10-04
- **Scope:** feature F-021
- **Premise:** The developer wants a daily spoken morning digest focused on tech-industry news. Almost everything already exists as configuration (connectors, sections, schedule, text-to-speech backends). But "tech-industry news only" cannot be expressed today, because the news RSS connector takes the first five items of every feed with no filtering. We offered a configuration-only setup, a full feature, or just tracking the work.
- **Decision:** Treat it as a full feature (F-021): local configuration plus a code change, taken through the orchestrator and every validation gate.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-021

## D-002 — The tech-news topic filter lives inside the news RSS connector

- **Date:** 2026-10-04
- **Scope:** feature F-021
- **Premise:** The World section should carry tech-industry news, and only the news RSS connector pulls general news. A filter could sit in three places: inside the connector, as a generic "topics" field on every digest section (applied in the digest collection tool), or as a hint in the language-model prompt. A prompt hint is not deterministic and still spends tokens on unrelated items. A generic section field spreads one concern over config, the collection tool, and every source.
- **Decision:** Add an optional `keywords` list to the news RSS connector's own config file (`news_rss.json`). When it is set, the connector scans a larger window of items per feed and keeps at most five whose title or description matches a keyword (case-insensitive, whole words). Without keywords it behaves exactly as before. The connectors API passes `keywords` through and rejects anything that is not a list of strings. The frontend connect screen is out of scope.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-021 (design.summary)

## D-003 — The digest voice is a Cartesia Indian-English female voice

- **Date:** 2026-10-04
- **Scope:** feature F-021
- **Premise:** The developer asked for an Indian female voice. The local Kokoro backend's Hindi female voices run through Kokoro's Hindi pronunciation model, which is likely to mangle an English briefing. Cartesia, a cloud service that is already the digest's default backend, offers Indian-English female voices but needs a `CARTESIA_API_KEY`. We chose quality of the English briefing over staying fully local for this one step.
- **Decision:** Use `tts_backend = "cartesia"` with an Indian-English female voice ID picked from Cartesia's voice catalog. No code change is needed, because the backend already accepts any voice ID.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-021; user's `~/.openjarvis/config.toml`

## D-004 — The digest runs at 07:00 India time

- **Date:** 2026-10-04
- **Scope:** feature F-021
- **Premise:** The digest's default timezone is America/Los_Angeles, but the developer's machine runs on India Standard Time and they asked for a 7am digest.
- **Decision:** Schedule the digest with cron `0 7 * * *` in timezone `Asia/Kolkata`.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-021; user's `~/.openjarvis/config.toml`

## D-005 — Accept existing size and import debt in files F-021 touched

- **Date:** 2026-10-04
- **Scope:** feature F-021
- **Premise:** The architecture review measures every file a change touches. F-021 had to edit the connectors API router and the news RSS connector. Both were already over the review's limits before this feature: the router was 1,020 lines (limit 500) and the connector had 16 imports (limit 15). F-021 added 9 router lines and one import (`re`). Splitting the router is a large refactor unrelated to the digest.
- **Decision:** Record these two static findings as accepted existing debt for F-021, rather than refactoring inside this feature. The review's language-model audit is still required and is not covered by this acceptance.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-021 (AC-006, blocker)

## D-006 — `jarvis connect` accepts a pasted token for token-based connectors

- **Date:** 2026-10-04
- **Scope:** feature F-022
- **Premise:** `jarvis connect notion` printed "No OAuth provider configured" and stopped. Notion, Slack, and Granola are labelled OAuth connectors, but they actually take a pasted token through the connector's own save method (`handle_callback`), and no OAuth provider exists for them. Four more connectors (Dropbox, Outlook, IMAP, Gmail over IMAP) hit the same dead end, but they need other input, such as an email and password, which the web UI already collects.
- **Decision:** Each paste-token connector declares a `paste_token_hint` telling the user where to get the token. When no OAuth provider exists and the connector has a hint, the CLI shows the hint, asks for the token with hidden input, and saves it through `handle_callback`, so Slack's and Granola's live validation still runs. Connectors without a hint get a clear message to use the web UI. The hint lives on the connector, so the CLI never needs a list of connector names.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-022

## D-007 — Keep the paste-token hint design despite the architecture audit

- **Date:** 2026-10-04
- **Scope:** feature F-022
- **Premise:** The architecture review's AI audit flagged the D-006 design. Whether a connector takes a pasted token now depends on two facts in two places: it has no OAuth provider, and it sets `paste_token_hint`. Meanwhile Notion, Slack, and Granola still declare `auth_type = "oauth"`. The audit suggested setting `auth_type = "token"` instead. That would touch the frontend connect screen, the connectors API router, and existing tests that assert "oauth". The audit also found that the web UI keeps a pasted Notion token in memory only. Separately, `slack_connector.py` was already 703 lines (limit 500) before this change.
- **Decision:** Keep the hint design. Accept the audit finding and Slack's existing file size as known trade-offs for F-022. Track the web-UI token bug as its own feature (F-023).
- **Supersedes:** none
- **Recorded in:** feature_list.json F-022, F-023

## D-008 — The scheduler daemon is the single, real runner of scheduled tasks

- **Date:** 2026-10-11
- **Scope:** feature F-024
- **Premise:** The 07:00 digest task sat in `~/.openjarvis/scheduler.db` for a week and never ran. `jarvis serve` does not start the task scheduler at all. `jarvis scheduler start`, which the docs tell users to run, builds the scheduler without a Jarvis system, so every due task is only logged as "[dry-run] Would execute". The developer chose a proper fix over a plain macOS timer that calls `jarvis digest --fresh`. Making `jarvis serve` the runner was rejected because schedules would then depend on a heavy server running all day; a separate macOS timer per task was rejected because the schedule would live in two places.
- **Decision:** `jarvis scheduler start` is the only process that runs scheduled tasks, and it runs them for real by building a fresh Jarvis system per run (so Ollama being down at boot or a config change needs no restart); `jarvis serve` does not run them, and a lock file refuses a second scheduler. The run log stores the reply text, and a task's next run time is advanced before it executes, so a slot runs at most once even if the run crashes.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-024

## D-009 — The scheduler runs as a macOS login service installed by the CLI

- **Date:** 2026-10-11
- **Scope:** feature F-024
- **Premise:** A scheduler started by hand in a terminal stops when the terminal closes or the Mac restarts, so a daily digest would silently stop. The repo already writes a launchd service file for `jarvis gateway start --install`.
- **Decision:** `jarvis scheduler start --install` (with `--uninstall` and a status command) writes a launchd login service that starts at login and restarts after a crash, reusing the gateway's service-file code; logs go to `~/.openjarvis/logs/`.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-024

## D-010 — The scheduler service reads the Cartesia key from the OpenJarvis credentials file

- **Date:** 2026-10-11
- **Scope:** feature F-024
- **Premise:** The digest's speech needs `CARTESIA_API_KEY`. The developer exports it from `~/.zshrc`, but launchd services do not read shell profiles. Putting the key in the service file would leave it in a file other users can read. OpenJarvis already has an owner-only `~/.openjarvis/credentials.toml` that `jarvis serve` loads at startup.
- **Decision:** The scheduler service loads `~/.openjarvis/credentials.toml` at startup, and the install command offers to copy the key there from the current shell; the key never goes into the service file. The macOS Keychain and reading the repo's `.env` were rejected as more code or tied to the repo path.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-024

## D-011 — Unattended runs need an agent allowlist and a tool allowlist

- **Date:** 2026-10-11
- **Scope:** feature F-024
- **Premise:** Once scheduled tasks really run, they run with nobody watching. Any task row can name any agent and any tool, and the developer's default tools include shell and code execution. An agent that reads email or RSS could then be steered by injected text into running commands. The digest agent itself never offers tools to the language model, so today's risk is small. The developer first chose an agent allowlist only; after the security reviewer's concern was raised again, they chose a tool allowlist rather than a tool ban, because the next feature will text them the digest and needs a messaging tool.
- **Decision:** Add `scheduler.allowed_agents` and `scheduler.allowed_tools`, both empty by default, so nothing runs unattended unless listed; tasks for other agents are skipped and logged, tools outside the list are unavailable in unattended runs, and agents cannot create scheduled tasks from inside the service. The developer's config lists the `morning_digest` agent and the `digest_collect` and `text_to_speech` tools.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-024

## D-012 — A missed digest plays only if the Mac wakes within 3 hours

- **Date:** 2026-10-11
- **Scope:** feature F-024
- **Premise:** Nothing runs while the Mac is asleep. Today the scheduler runs an overdue task as soon as it can, which could speak a "morning" digest late at night. Other scheduled tasks may want to catch up.
- **Decision:** Each task may set a grace window for late runs; a task later than its window is skipped and logged as missed, and tasks without one keep catching up. The digest task gets 3 hours, so it plays if the Mac wakes by 10:00 India time.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-024

## D-013 — A digest-owned listener speaks the scheduled digest when autoplay is on

- **Date:** 2026-10-11
- **Scope:** feature F-024
- **Premise:** The developer wants the 07:00 digest spoken aloud on the Mac. Playing audio inside the digest agent would also play it for web and API requests, and twice for `jarvis digest --fresh`. The scheduler is generic and should not know about digests or audio.
- **Decision:** A listener owned by the digest code reacts to the scheduler's "task finished" event and plays the fresh audio when the run succeeded, the agent is `morning_digest`, and the new `digest.autoplay` setting is on. The setting is off by default and on in the developer's config.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-024

## D-014 — The architecture review no longer gates on file length

- **Date:** 2026-10-11
- **Scope:** architecture
- **Premise:** The architecture review failed any changed source file over 500 lines. F-024 made small, necessary edits to three files that were already longer than that (`core/config.py`, `tools/_stubs.py`, and an operators test), and earlier features had to accept the same failure as debt (D-005, D-007). The developer's view is that the project's first architecture rule judges a module by how simple its interface is compared with the complexity it hides, and a line count does not measure that; splitting a deep module only to get under a limit makes it shallower.
- **Decision:** Remove the 500-line check from `scripts/architecture-review.sh` and say so in `docs/architecture-rules.md`; the import-count check, the complexity check, and the language-model audit against the architecture rules stay.
- **Supersedes:** the file-length parts of D-005 and D-007 (their import-count and audit findings still stand)
- **Recorded in:** docs/architecture-rules.md "Enforcement"; scripts/architecture-review.sh

## D-015 — Accept two architecture-audit points on F-024 as known debt

- **Date:** 2026-10-11
- **Scope:** feature F-024
- **Premise:** Over five rounds the architecture review's language-model audit kept raising new points on F-024; every substantive one was fixed. Two remaining points are about shape rather than behaviour: the macOS service-file generator's arguments map almost one-to-one onto service-file keys, so it hides little; and a scheduled run's outcome travels between the scheduler and its policy as tuples and plain strings rather than one typed record. Both are covered by tests and neither changes what the user sees.
- **Decision:** Record both as known debt for F-024 and move on rather than run another redesign round.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-024 (AC-007)

## D-016 — The architecture review no longer gates on import count

- **Date:** 2026-10-11
- **Scope:** architecture
- **Premise:** After D-014 removed the file-length check, the architecture review still failed any changed source file with more than 15 import lines. The only remaining failure across F-021 and F-024 was the news RSS connector at 17 imports (16 before F-021), which fetches feeds over a path hardened against requests to private addresses and also parses RSS. Clearing it would have meant moving security-sensitive fetching code purely to satisfy the count. The developer applied the same reasoning as D-014: information leakage is about what a module exposes and depends on, which the language-model audit judges against the architecture rules, and a count of import lines does not measure it.
- **Decision:** Remove the import-count check from `scripts/architecture-review.sh` and say so in `docs/architecture-rules.md`; the complexity check (when `radon` is installed) and the language-model audit remain the gate.
- **Supersedes:** the import-count parts of D-005 and D-007
- **Recorded in:** docs/architecture-rules.md "Enforcement"; scripts/architecture-review.sh

## D-017 — Pay down the debt the architecture audit keeps re-flagging

- **Date:** 2026-10-11
- **Scope:** features F-022, F-024
- **Premise:** F-021 and F-024 passed every check except the architecture review's language-model audit, which kept raising three points the developer had accepted as debt: a scheduled run's outcome travels as tuples and bare strings although a `RunRecord` type exists (D-015); the macOS service-file generator takes raw launchd keys, so callers must know launchd's semantics (D-015); and whether `jarvis connect` asks for a pasted token is decided by whether the help text `paste_token_hint` is empty (D-006, D-007). Rather than keep accepting them, the developer chose to fix them. For the third point, adding an explicit flag was preferred over changing `auth_type` to "token", because the web UI connect screen, the connectors API, and their tests all rely on `auth_type` and F-023 will revisit that path.
- **Decision:** The scheduler owns one `RunOutcome` set of values and passes `RunRecord` through its internal steps, with the store deriving the old success flag from the outcome and filling an outcome for old rows; the service-file generator takes intent (restart on crash, minimum restart interval) instead of raw launchd keys; and Notion, Slack, and Granola declare `accepts_pasted_token = True`, which alone decides the paste-token flow, while `paste_token_hint` is only the help text and `auth_type` stays "oauth".
- **Supersedes:** D-015 (both points); the part of D-006 and D-007 where the hint's presence decides the flow
- **Recorded in:** feature_list.json F-022, F-024
