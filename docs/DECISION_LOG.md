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

## D-018 — WhatsApp business updates are read from the WhatsApp Mac app's local database

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** Many businesses in India send order, delivery and appointment updates on WhatsApp, and the developer wants them in the morning digest. The existing `whatsapp` connector only reads chats exported by hand, so it is never fresh at 07:00, and the digest builds it without an export folder, so it never connects. The live alternative, Baileys, pretends to be WhatsApp Web: that breaks WhatsApp's terms, Baileys users report restriction warnings even without bulk sending, and this repo's roadmap already marks it Blocked after WhatsApp rejected its connections in February 2026. The official WhatsApp Business Cloud API cannot read a personal inbox at all. The WhatsApp Mac app keeps its data in plain SQLite files on disk, the same way the iMessage connector reads `chat.db`, and reading them puts the developer's personal number at no risk.
- **Decision:** Read WhatsApp messages read-only from the WhatsApp Mac app's local data (`~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/`); do not use Baileys or hand exports for the digest.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025; docs/ARCHITECTURE.md design decisions

## D-019 — A chat counts as a business from WhatsApp's own business records, with approval for profile-only chats

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** The developer requires personal chats to be strictly excluded, so the digest must know which senders are businesses rather than guess. The Mac app stores this in `Biz/Biz.sqlite`: one table lists accounts with a WhatsApp-certified business name (82 of the developer's 454 one-to-one chats), another lists accounts with only a business profile (117 more). Profile-only accounts are typically small businesses on the WhatsApp Business app, which can include friends or relatives who run a shop or practice. Guessing from names, keywords or a language model would eventually let a personal chat through.
- **Decision:** Chats with a certified business name are included automatically; profile-only chats are included only after the developer approves them; an exclude list always wins; group chats, status updates, broadcasts and WhatsApp Channels are never included.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025

## D-020 — The WhatsApp section carries transactional updates only, with sensitive details redacted

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** Business WhatsApp traffic is mostly advertising, which is noise in a spoken briefing. What matters is what the developer would regret missing: an order arriving, an appointment, a booking, a bill coming due. Confirmations of payments already made only repeat what the developer did, and they carry the most sensitive details.
- **Decision:** Keep orders and deliveries, appointments and reservations, travel bookings, and bills, recharges, credit card and EMI payments that are due; drop promotions, one-time codes and confirmations of payments already made; redact card numbers, one-time codes and addresses everywhere.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025

## D-021 — WhatsApp content is processed locally, and only redacted lines reach the cloud voice

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** The digest is written by local Ollama, but the finished script is spoken by Cartesia, a cloud text-to-speech service (D-003). Anything from WhatsApp in the script therefore leaves the laptop. The developer wants the Cartesia voice to stay, but not their order numbers, amounts or addresses sent with it.
- **Decision:** Sorting and summarising WhatsApp messages runs only on the local engine; the text sent to Cartesia contains only redacted "business name: status" lines; if the local engine is unreachable or the default engine is a cloud model, the WhatsApp section is skipped rather than sent to the cloud.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025; docs/ARCHITECTURE.md design decisions

## D-022 — A new `whatsapp_desktop` connector owns the business filter

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** The existing `whatsapp` connector reads exported text files and returns one document per whole chat, which is the wrong shape for a digest. Replacing it would break chat search for anyone using exports. If the business filter lived in the digest code, every future caller of the connector would have to remember to apply it, and a personal chat could leak through one that forgets.
- **Decision:** Add a separate `whatsapp_desktop` connector, modelled on the iMessage connector, that returns one document per message from business chats only, with business status and verified name in its metadata; the export connector stays unchanged.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025; docs/ARCHITECTURE.md design decisions

## D-023 — Profile-only businesses are approved with `jarvis whatsapp review`

- **Date:** 2026-10-11
- **Scope:** features F-025, F-026
- **Premise:** Because profile-only chats need approval (D-019), the developer needs a way to approve or exclude them, and new businesses keep appearing. Naming new senders in the digest would reveal chats the developer has not approved.
- **Decision:** A `jarvis whatsapp review` command lists suggested businesses with name, category and last-message date only, and saves decisions to `~/.openjarvis/whatsapp_businesses.toml`, which can also be edited by hand; the digest only says how many businesses await review. A review screen in the web UI is a separate later feature (F-026).
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025, F-026

## D-024 — WhatsApp gets its own digest section with latest status and a short look-ahead

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** One order can produce several messages in a day ("shipped", then "out for delivery"), and reading each aloud is tedious. The digest looks back 24 hours, but a bill due date or an appointment confirmed a week ago matters on the day itself. The developer preferred a section of its own over a block inside Messages.
- **Decision:** A top-level WHATSAPP section, spoken after Calendar, shows the latest status per order or booking from the last 24 hours plus due dates and appointments in the next 48 hours found in the last 14 days, at most about 8 items, soonest first.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025

## D-025 — OpenJarvis opens WhatsApp before the digest and warns when its data is stale

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** The WhatsApp Mac app only downloads new messages while it is running. If it is closed overnight, the 07:00 digest would silently miss everything since. macOS can open an app in the background without taking focus (`open -g`).
- **Decision:** The scheduler opens WhatsApp in the background about 15 minutes before the digest; if the newest message is still more than 12 hours old, the digest says so and `jarvis doctor` flags it.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025

## D-026 — The WhatsApp source fails closed when it cannot be sure

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** The Mac app's database layout is undocumented and can change with any WhatsApp update. If the connector misread a changed layout, it could treat personal chats as business chats. Business updates arrive in one-to-one chats, so groups, broadcasts and WhatsApp Channels add risk without adding the updates the developer asked for.
- **Decision:** When the database layout is not the one the connector recognises, it reports "unsupported version" and returns nothing rather than reading without the business filter; groups, broadcasts, status updates and Channels are always excluded.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-025

## D-027 — Promotions are dropped by Meta's template category before the local model runs

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** The template-message spike (F-027) found that every template message a business sends carries Meta's own category label, `UTILITY` or `MARKETING`, inside the message data, on seven message types. Businesses must declare this category to Meta, so it is a far more reliable signal than asking a language model whether a message is an advert. Plain-text messages carry no category.
- **Decision:** The `whatsapp_desktop` source drops any message whose template category is `MARKETING` before the local model sees it; the local model still sorts messages without a category.
- **Supersedes:** none (refines how D-020's "drop promotions" is carried out)
- **Recorded in:** feature_list.json F-025; docs/spikes/whatsapp/FINDINGS.md

## D-028 — Profile-only chats that send utility templates are pre-approved but stay reviewable

- **Date:** 2026-10-11
- **Scope:** feature F-025
- **Premise:** Under D-019, chats with only a business profile need the developer's approval, because a friend running a shop on the WhatsApp Business app also has a business profile. The spike found 292 `UTILITY` template messages from profile-only chats. Only businesses on Meta's WhatsApp Business Platform can send template messages at all, which friends on the ordinary WhatsApp Business app cannot, so these senders are almost certainly real businesses. Requiring manual approval for all of them would make the review list long for little safety gain.
- **Decision:** A profile-only chat that has sent at least one `UTILITY` template is pre-approved, and is still listed in `jarvis whatsapp review` so the developer can exclude it; other profile-only chats still need explicit approval.
- **Supersedes:** the profile-only part of D-019, for chats that have sent `UTILITY` templates
- **Recorded in:** feature_list.json F-025; docs/spikes/whatsapp/FINDINGS.md

## D-029 — Every agent run goes into a disposable OpenShell sandbox; the host keeps the scheduler and server

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** The developer wants to treat OpenJarvis agents as untrusted code, so a security issue or a risky command damages as little as possible. OpenShell (NVIDIA's policy-governed sandbox runtime, installed locally as 0.0.21) can run each agent in its own sandbox with network and filesystem rules. We could have sandboxed all of OpenJarvis, only risky tools, or each agent run. Sandboxing all of OpenJarvis would put every connector secret and the scheduler database inside one long-lived sandbox. The existing `SandboxedAgent` wrapper and `[sandbox] runtime` setting already give a place to plug in a new runtime.
- **Decision:** Add OpenShell as a runtime behind `SandboxedAgent`; every agent run, including interactive chat, executes in an OpenShell sandbox, while the scheduler, `jarvis serve`, and the CLI stay on the host.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030; docs/superpowers/specs/2026-11-01-openshell-sandbox-design.md

## D-030 — Sandboxes come from a warm pool and are used once

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** Creating an OpenShell sandbox goes through the gateway and the Podman virtual machine and is expected to take seconds. Since chat is sandboxed too, creating one per message would delay every reply. Keeping one sandbox per chat session would be faster, but it would let injected content build up across a conversation. A pool of sandboxes created ahead of time keeps each run clean without making the user wait.
- **Decision:** The host process that runs agents keeps a pool of pre-created sandboxes (default two, configurable); each run claims one, the sandbox is deleted after that run, the pool refills in the background, and it is drained on shutdown.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030

## D-031 — Pooled sandboxes start deny-all and get the agent's policy when claimed

- **Date:** 2026-11-01
- **Scope:** feature F-029, F-030
- **Premise:** OpenShell sets a sandbox's policy and providers (its credential bundles) when it creates the sandbox. A pooled sandbox is created before anyone knows which agent will use it, which conflicts with giving each agent its own rules (D-035). OpenShell can change the policy of a live sandbox (`openshell policy set`). We do not yet know whether a provider can be attached after a sandbox is created.
- **Decision:** Pooled sandboxes start with a deny-all policy and no providers; when an agent claims one, the host applies that agent's policy and uploads that run's short-lived tokens, and the spike (F-029) must confirm this works and that nothing can leave the network before the policy is applied.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-029, F-030

## D-032 — If OpenShell is unavailable, the run is refused

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** The OpenShell gateway and the Podman virtual machine must be running for a sandboxed run to work, including the unattended 07:00 digest. Quietly running the agent on the host instead would undo the protection without anyone noticing. Starting the gateway automatically was also considered.
- **Decision:** When the gateway or the container runtime is unavailable, the agent run is refused with a clear error and `jarvis doctor` reports why; there is never a fallback to running on the host.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030

## D-033 — Model calls go through the OpenShell gateway, which forwards to OpenJarvis on the host

- **Date:** 2026-11-01
- **Scope:** feature F-031
- **Premise:** A sandboxed agent cannot reach Ollama on the host by default. The developer chose OpenShell's inference gateway so the sandbox never holds API keys. OpenJarvis treats energy, tokens, latency, and dollar cost as first-class measurements, and records them per call in the engine layer. If the gateway called Ollama or a cloud provider directly, sandboxed runs (which is every run) would lose that telemetry and the local-versus-cloud engine choice. OpenJarvis already serves an OpenAI-compatible `/v1/chat/completions` endpoint.
- **Decision:** Sandboxes reach models only through the OpenShell inference gateway, whose upstream is OpenJarvis's `/v1/chat/completions` on the host, so engine selection and telemetry stay where they are today; that endpoint must accept calls only from the gateway.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-031

## D-034 — Tools and connectors run inside the sandbox, with short-lived, minimum-permission tokens

- **Date:** 2026-11-01
- **Scope:** feature F-032, F-033
- **Premise:** Many agents use connectors that need personal-data credentials (Gmail, Calendar). Keeping connectors on the host behind an allowlisted endpoint would keep credentials out of the sandbox, but it means building a host-side tool-call service. The developer preferred to run everything inside the sandbox. The risk we pointed out still applies: a prompt-injected agent holding a Gmail token can misuse it through a destination the policy has to allow, and the sandbox cannot tell the difference.
- **Decision:** All tools run inside the sandbox; the host mints short-lived access tokens per run (refresh tokens never enter a sandbox), each agent gets minimum OAuth permissions and only the credentials its config names, its policy allows only the exact API hosts those connectors need, and text-to-speech playback and WhatsApp reading happen on the host after the run. Misuse of a live token through an allowed host, until it expires, is an accepted trade-off.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-032, F-033

## D-035 — Each agent's OpenShell policy is generated from OpenJarvis config

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** Every agent needs its own network and credential rules. Hand-written OpenShell policy files per agent would spread security rules across loose files that tests cannot easily check. One global policy would give every agent the union of all permissions.
- **Decision:** Generate each agent's policy YAML from `[sandbox.agents.<id>]` in OpenJarvis config (`allowed_hosts`, `providers`), applied on top of a built-in deny-all base.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030

## D-036 — Memory goes in as a read-only snapshot; only the host writes SQLite

- **Date:** 2026-11-01
- **Scope:** feature F-033
- **Premise:** Agent memory, traces, and telemetry live in SQLite on the host. A disposable sandbox loses anything written inside it. Letting the sandbox write memory back would let an untrusted agent corrupt long-lived state. Running agents with no memory would make them much less useful.
- **Decision:** The host uploads a read-only snapshot of only the memory and context the run needs; the result, traces, and output files come back, and only the host writes to its SQLite databases.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-033

## D-037 — The OpenShell sandbox image is built from the existing sandbox Dockerfile

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** `deploy/docker/Dockerfile.sandbox` already defines the image used by the Docker sandbox. `openshell sandbox create --from <path>` can build an image from a Dockerfile. Publishing to a registry or installing OpenJarvis when the sandbox starts would add release work or startup time.
- **Decision:** OpenShell sandboxes are built from `deploy/docker/Dockerfile.sandbox` through `--from`, so there is one image definition for both runtimes.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030

## D-038 — OpenShell sandboxing ships as a spike plus four features

- **Date:** 2026-11-01
- **Scope:** feature F-029 – F-033
- **Premise:** The design relies on OpenShell 0.0.21 behaving in specific ways on macOS with Podman: how long creating a sandbox takes, applying a policy to a live sandbox, attaching providers after creation, and pointing the gateway's inference upstream at OpenJarvis. If any of these is wrong, the design changes. The work also covers several separable concerns.
- **Decision:** Run a spike first (F-029), then build the OpenShell runner and pool (F-030), model access through the gateway (F-031), connector credentials (F-032), and the host-side work before and after each run (F-033).
- **Supersedes:** none
- **Recorded in:** feature_list.json F-029 – F-033

## D-039 — Personal-data connectors run on the host; sandboxes hold no real credentials

- **Date:** 2026-11-01
- **Scope:** feature F-032
- **Premise:** D-034 put all tools, including Gmail and Calendar connectors, inside the sandbox with scoped short-lived tokens. The spike (F-029) found that OpenShell substitutes an attached provider's real credential into headers and URL queries sent to *every* allowed host, not only that provider's service, and that this cannot be switched off per host. The security review added that Google APIs echo invalid query values in error messages, so an injected agent could end up holding the token in plain text. A digest sandbox that allows Gmail and news sites would hand a live Gmail token to any of those sites.
- **Decision:** Personal-data connectors run on the host behind a narrow tool endpoint; each run gets a short-lived, run-scoped key that only allows that agent's allowlisted tool calls, and every call is audited; sandboxes never hold a real credential and OpenShell providers are not used for personal data.
- **Supersedes:** D-034
- **Recorded in:** feature_list.json F-032; docs/spikes/openshell/FINDINGS.md (Q4, F1)

## D-040 — One pool keyed by agent policy and image; pool size per agent

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** D-031 applied each agent's policy to a generic deny-all sandbox when claimed. The spike measured 2–10 s for each live policy change, which would land on every run, chat included. Creating a sandbox with its policy takes about 2 s once the image is cached. With credentials moved to the host (D-039), pooled sandboxes no longer hold tokens while idle. The architect review noted that separate pools per agent type would not fit the 4-CPU, 8 GiB Podman VM if every agent kept a sandbox warm.
- **Decision:** A single pool keyed by the agent's generated policy and the image version; each agent has a pool size (1 for interactive agents such as chat, 0 meaning create on demand for scheduled agents); sandboxes are created with their agent's policy, the host checks the policy version before handing one out, a config change yields a new key, and each sandbox is still used once.
- **Supersedes:** D-031, and the fixed "default two" pool size in D-030
- **Recorded in:** feature_list.json F-030

## D-041 — A slim, dedicated OpenShell image built outside the request path

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** D-037 reused `deploy/docker/Dockerfile.sandbox` through `openshell sandbox create --from`. The spike found OpenShell uses the Dockerfile's own directory as the build context (that Dockerfile needs the repository root, and the repo has no `.dockerignore`), and that every image must contain a `sandbox` user and group. The community `base` image ships Python 3.14, which OpenJarvis does not support, and is 1.13 GB; its first pull took 29 minutes. The security review asked for a digest-pinned base and a minimal build context so no secrets are baked in.
- **Decision:** A new slim OpenShell image (`python:3.12-slim` pinned by digest, a `sandbox` user, `/sandbox` work directory, OpenJarvis installed from `uv.lock` with hashes) built from its own small build directory with a `.dockerignore`, in a separate build step that `jarvis doctor` reports on; a local registry is the fallback if OpenShell rebuilds on every create.
- **Supersedes:** D-037
- **Recorded in:** feature_list.json F-030; docs/spikes/openshell/FINDINGS.md (B3, B4)

## D-042 — OpenShell runs in a dedicated Podman machine with no macOS folders mounted

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** The OpenShell gateway only starts on a rootful Podman machine. The developer's existing machine mounts macOS `/Users` read-write into the VM, as Podman does by default. A sandbox escape to root in the VM would then reach `~/.openjarvis` and the rest of the home directory.
- **Decision:** OpenShell gets its own rootful Podman machine with no host folders mounted; `jarvis doctor` checks for it.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030; docs/spikes/openshell/FINDINGS.md (B1, F4)

## D-043 — The gateway uses a separate key on a pass-through model endpoint

- **Date:** 2026-11-01
- **Scope:** feature F-031
- **Premise:** D-033 routes sandboxed model calls through the OpenShell gateway to OpenJarvis `/v1`. The spike showed the agent-wrapped `/v1/chat/completions` turned a one-line question into 13,351 prompt tokens, that the gateway forces one model for every sandbox, and that `inference.local` stays reachable even under a deny-all policy. The security review pointed out that giving the gateway the full `OPENJARVIS_API_KEY` exposes the whole API to any process or container holding it, and that an injected agent could push personal data to a cloud engine if the request could choose the engine.
- **Decision:** The gateway gets its own key that only works on a new pass-through model endpoint; the host fixes the engine and model regardless of the request and enforces a per-run budget.
- **Supersedes:** none (refines D-033)
- **Recorded in:** feature_list.json F-031

## D-044 — Every agent is constructed through one factory that applies the sandbox

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** During F-030 implementation the developer was shown that `SystemBuilder` builds a `ContainerRunner` that no code ever uses: nothing wraps an agent in `SandboxedAgent`, so `[sandbox] enabled = true` has no effect today. Agents are constructed in about eight places (`cli/ask.py`, `cli/chat_cmd.py`, `cli/serve.py`, `sdk.py`, `system/orchestrator.py`, `agents/executor.py` twice, `agents/hybrid/runner.py`). Options offered: one factory every site calls, a hook in `AgentRegistry.get`, or wiring only the server and scheduler paths.
- **Decision:** One agent factory in `agents/` that every construction site calls; it wraps the agent in `SandboxedAgent` with the OpenShell runner when `[sandbox] runtime = "openshell"`. Chosen by the developer over the registry hook (too implicit) and partial wiring (leaves CLI runs on the host).
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030

## D-045 — Wire the OpenShell runner in before the entrypoint and model access exist

- **Date:** 2026-11-01
- **Scope:** feature F-030
- **Premise:** A sandboxed agent needs an in-sandbox entrypoint (the existing `Dockerfile.sandbox` names an `openjarvis.sandbox.entrypoint` module that does not exist) and model access through the gateway (F-031). Options offered: build the image and entrypoint first and keep wiring off until F-031; wire now; or pull F-031 into F-030.
- **Decision:** Wire the runner into every agent construction path now. With `runtime = "openshell"`, runs fail closed with a clear error until the entrypoint and F-031 land; the default runtime is unchanged, so nothing changes for users who have not opted in.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030

## D-046 — Move the gateway to a dedicated machine; mounted host folders warn rather than refuse

- **Date:** 2026-11-02
- **Scope:** feature F-030
- **Premise:** Completing F-030, the developer was shown that the gateway ran on `podman-machine-default`, which mounts `/Users`, `/private` and `/var/folders` read-write into the VM, so code that escaped a sandbox could reach the home directory (the D-042 threat). Options offered for the machine: migrate now to a new rootful machine with no mounts, or keep the default machine and only report it. Options for the doctor/pre-flight policy on mounts: refuse runs, or warn.
- **Decision:** Migrate: a rootful `openshell` machine created with `--volume ""`, gateway rebuilt there, image rebuilt. Mounted host folders are a `jarvis doctor` warning and do not refuse runs; a missing, rootless or stopped machine, a disconnected gateway and a missing image do refuse.
- **Supersedes:** none (implements D-042)
- **Recorded in:** feature_list.json F-030; docs/user-guide/openshell-sandbox.md

## D-047 — Patch the inherited dependency advisories on the F-030 branch

- **Date:** 2026-11-02
- **Scope:** feature F-030 (uv.lock)
- **Premise:** The security gate failed on 27 pip-audit advisories in aiohttp, certifi, filelock and virtualenv, all already in `uv.lock` on the base branch and unrelated to F-030. The sandbox image is built from the same lock, so it shipped the vulnerable aiohttp. Options offered: upgrade the four packages on this branch, fix them in a separate PR against the base, or leave F-030 unverified.
- **Decision:** Upgrade only those four packages on this branch (`uv lock --upgrade-package`), rerun every gate and rebuild the image. filelock 4.2.x needs Python 3.11, so Python 3.10 keeps filelock 4.1.0 and the advisories fixed in 4.2.1; accepted because CI and the image use 3.12/3.13 and the 3.10 unit failure set is unchanged.
- **Supersedes:** none
- **Recorded in:** feature_list.json F-030
