# Product — OpenJarvis

> Why this project exists, who it serves, and what's in/out of scope. Update when the user story or scope changes.

## Intent

OpenJarvis is a local-first personal AI framework ("Personal AI, On Personal Devices"). It provides shared primitives — engines, agents, tools, memory, learning — for building on-device agents, treats energy / FLOPs / latency / dollar cost as first-class constraints alongside accuracy, improves models from local trace data, and calls the cloud only when necessary. It serves as both a research platform and a production foundation.

## Primary user story

Privacy-conscious individuals and developers run a personal assistant on their own laptop or workstation — chat, a spoken morning digest, deep research, coding help, scheduled monitoring — and reach it from their phone via messaging channels. Researchers use it to benchmark local vs. cloud models on cost and energy.

## Jobs to be done

- When I start my day, I want a spoken briefing of messages, calendar, health, and world news, so that I'm oriented without opening five apps.
- When my briefing covers world news, I want it narrowed to the topics I follow (for example, tech-industry keywords on my RSS feeds), read in a voice and at a local time I choose, so that it is relevant without manual curation (F-021).
- When businesses message me on WhatsApp (common in India), I want my briefing to tell me about orders and deliveries, appointments and reservations, travel bookings, and bills or EMIs coming due, from business accounts only, with promotions dropped, personal chats never read, and card numbers, one-time codes and addresses redacted, so that I don't miss what matters in a flood of business messages (F-025). Open questions: whether template-style business messages can be decoded, and whether the background scheduler service gets macOS permission to read WhatsApp's data.
- When I research a topic, I want an agent that searches and synthesizes sources, so that I get a cited summary without manual browsing.
- When I chat with an assistant, I want it to run on my own hardware, so that my personal data never leaves my device unless I choose.
- When I evaluate models, I want energy, latency, and cost measured alongside accuracy, so that I can pick the right local/cloud trade-off.
- {{TODO: additional jobs}}

## Scope

### In scope

- Local inference across multiple engines, with cloud fallback
- Agents (digest, deep research, orchestrator, hybrid) and tools
- Personal-data connectors and memory/retrieval
- Messaging channels, CLI, web UI, desktop app, optional HTTP server
- Telemetry (energy, latency, cost), evals, benchmarks, learning loop
- Security guardrails and sandboxed tool execution

### Out of scope

{{TODO: bullet list of things this project deliberately does NOT do (e.g. multi-tenant hosted SaaS, training foundation models from scratch).}}

## Success metrics

- **Adoption:** {{TODO}}
- **Engagement:** {{TODO}}
- **Reliability:** {{TODO}}
- **Performance:** see [RELIABILITY.md](RELIABILITY.md)

## Feature inventory

The canonical list of features lives in [feature_list.json](../feature_list.json). Each feature has a `status` (`pass` / `partial` / `todo` / `fail`) and concrete `evidence`. Keep that file in sync with reality. See also `docs/development/roadmap.md`.

## Roadmap

{{TODO: ordered list of what's next. Reconcile with docs/development/roadmap.md.}}

## Non-users / anti-personas

{{TODO: who is this NOT for?}}
