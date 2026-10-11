# WhatsApp Mac database spikes (F-027, F-028)

Run on 2026-10-11 against the developer's WhatsApp Mac app data (`~/Library/Group Containers/group.net.whatsapp.WhatsApp.shared/`). Everything was opened read-only (`mode=ro`). The scripts print only counts, field paths, timings and digit-masked, truncated previews. No raw message text was printed or stored. They read real personal data, so run them only on your own machine.

## F-027: text inside template messages (type 19)

**Answer: yes, the text can be extracted reliably.** `ZWAMEDIAITEM.ZMETADATA` is a protobuf message. A schema-less walk over its length-delimited fields recovers the body in 66 of 68 type-19 messages from certified businesses (last 30 days).

Field layout (paths are protobuf field numbers):

| Path | Meaning | Seen in (of 68) |
|------|---------|-----------------|
| `24` | Template message wrapper (the only top-level field) | 68 |
| `24.1.2` | Header / title (e.g. "Payment Update") | 6 |
| `24.1.6` | **Body text** | 66 |
| `24.1.7` | Footer (e.g. "Reply STOP to unsubscribe") | 46 |
| `24.1.8.1.*` | Quick-reply buttons (label, payload) | 26 |
| `24.1.8.2.1` / `24.1.8.2.2` | URL button label / URL | 49 |
| `24.6` | Template ID (numeric string) | 61 |
| `24.7` | **Template category: `UTILITY` or `MARKETING`** | 68 |

Decoder rules learned:

- Treat `24`, `24.1` and `24.1.8*` as submessages even when their bytes happen to decode as UTF-8. Otherwise the body is misread as one string; the first pass lost 4 bodies this way.
- Button payloads can be JSON carrying shipment or order IDs. They must go through redaction like the body.

**Bonus finding: template category.** Field `24.7` is Meta's own template category. Across all one-to-one chats and all time (`category_census.py`), it appears on message types 13, 19, 20, 24, 41, 42 and 43:

| Sender tier | UTILITY | MARKETING |
|-------------|---------|-----------|
| Certified business name | 189 | 114 |
| Business profile only | 292 | 120 |
| Not in business tables | 0 | 1 |

Implications for F-025:

1. `MARKETING` messages are dropped deterministically before the local model runs (agreed, D-027).
2. Only businesses on Meta's WhatsApp Business Platform can send template messages, so a profile-only sender of `UTILITY` templates is almost certainly not a friend using the WhatsApp Business app. Such chats are pre-approved but stay reviewable (agreed, D-028).
3. One marketing template came from a chat with no business record. The account-ID mapping table `LID.sqlite` → `ZWAPHONENUMBERLIDPAIR` is **empty** on this machine, so the connector must not rely on it. It must match both `ZJID` and `ZPHONENUMBERJID` from `Biz.sqlite`, and treat anything unmatched as personal (fail closed).

Two type-19 bodies were not at `24.1.6`. The connector should fall back to "update from <business>" for those, as already designed.

Reproduce: `python3 docs/spikes/whatsapp/decode_type19.py 30` and `cd docs/spikes/whatsapp && python3 category_census.py`.

## F-028: can the launchd scheduler service read the data?

**Answer: yes, with no extra permission.** A real launchd job, `com.openjarvis.spike-wa-access`, ran with parent PID 1 and the scheduler service's own interpreter (`~/.openjarvis/.venv/bin/python` → uv CPython 3.13.1). It opened `ChatStorage.sqlite` (558 chats), `Biz/Biz.sqlite` (199 certified-name rows) and `LID.sqlite` read-only, with no macOS prompt. The same job could **not** open the macOS permissions database (`TCC.db`), which proves it has no Full Disk Access, and none is needed.

Observations:

- The first access to the folder in a process costs about 1–2 s. Later opens are instant, which suggests a per-process macOS privacy check. The first-ever access from a new interpreter took about 22 s once, then about 1 s.
- Apple can tighten app-data protection in a future macOS release. F-025 should therefore treat `PermissionError` and `sqlite3.OperationalError: unable to open database file` as "permission missing". It should skip the section (fail closed), and `jarvis doctor` should tell the user to grant Full Disk Access to the scheduler's Python, giving the real path from `os.path.realpath(sys.executable)`.

Reproduce: `launchctl bootstrap gui/$(id -u) docs/spikes/whatsapp/com.openjarvis.spike-wa-access.plist`, read `/tmp/wa_spike/launchd_result.txt`, then `launchctl bootout gui/$(id -u)/com.openjarvis.spike-wa-access`. The plist expects the probe at `/tmp/wa_spike/launchd_probe.py`; copy it there first.
