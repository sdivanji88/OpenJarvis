"""F-027 spike: schema-less decode of WhatsApp type-19 ZMETADATA blobs.

Read-only. Certified-business chats only. Prints field paths, counts and
digit-masked, truncated previews -- never raw message text.
"""

import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path.home() / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared"
APPLE_EPOCH = 978307200
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 30


def varint(buf, i):
    shift = result = 0
    while True:
        if i >= len(buf):
            raise ValueError("truncated varint")
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def parse(buf, depth=0):
    """Return list of (field_no, wire, value) or raise if not a valid message."""
    out, i = [], 0
    while i < len(buf):
        key, i = varint(buf, i)
        field, wire = key >> 3, key & 7
        if field == 0:
            raise ValueError("field 0")
        if wire == 0:
            v, i = varint(buf, i)
        elif wire == 1:
            v, i = buf[i : i + 8], i + 8
        elif wire == 5:
            v, i = buf[i : i + 4], i + 4
        elif wire == 2:
            n, i = varint(buf, i)
            if i + n > len(buf):
                raise ValueError("overrun")
            v, i = buf[i : i + n], i + n
        else:
            raise ValueError(f"wire {wire}")
        out.append((field, wire, v))
    return out


def strings(buf, path="", depth=0):
    """Yield (path, text) for every UTF-8 text leaf, recursing into submessages."""
    try:
        fields = parse(buf)
    except ValueError:
        return
    for field, wire, v in fields:
        p = f"{path}.{field}" if path else str(field)
        if wire != 2:
            continue
        nested = None
        if depth < 8 and v:
            try:
                nested = parse(v)
            except ValueError:
                nested = None
        text = None
        try:
            t = v.decode("utf-8")
            if t and sum(c.isprintable() or c in "\n\t" for c in t) / len(t) > 0.95:
                text = t
        except UnicodeDecodeError:
            pass
        # Known submessage wrappers (24, 24.1, 24.1.8*) must recurse even if
        # their bytes happen to decode as UTF-8.
        if nested is not None and p in FORCE_NESTED:
            yield from strings(v, p, depth + 1)
        # Prefer text when it reads like language; protobuf can mis-parse text.
        elif text and re.search(r"[A-Za-z\u0900-\u097F]{3}", text):
            yield p, text
        elif nested is not None:
            yield from strings(v, p, depth + 1)
        elif text:
            yield p, text


FORCE_NESTED = {"24", "24.1", "24.1.8", "24.1.8.1", "24.1.8.2"}


def mask(t, n=70):
    t = re.sub(r"\d", "#", t)
    t = re.sub(r"\S+@\S+", "<email>", t)
    t = re.sub(r"https?://\S+", "<url>", t)
    t = t.replace("\n", " / ")
    return t[:n] + ("..." if len(t) > n else "")


con = sqlite3.connect(f"file:{ROOT / 'ChatStorage.sqlite'}?mode=ro", uri=True)
con.execute(f"ATTACH 'file:{ROOT / 'Biz/Biz.sqlite'}?mode=ro' AS biz")
rows = con.execute(
    """
    WITH certified AS (
      SELECT ZJID AS jid FROM biz.ZWABIZVERIFIEDNAMEDATA
      UNION SELECT ZPHONENUMBERJID FROM biz.ZWABIZVERIFIEDNAMEDATA
        WHERE ZPHONENUMBERJID IS NOT NULL
    )
    SELECT m.Z_PK, mi.ZMETADATA
    FROM ZWAMESSAGE m
    JOIN ZWACHATSESSION c ON m.ZCHATSESSION = c.Z_PK
    JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM
    WHERE c.ZSESSIONTYPE = 0 AND m.ZISFROMME = 0 AND m.ZMESSAGETYPE = 19
      AND m.ZMESSAGEDATE > (strftime('%s','now') - ? - ? * 86400)
      AND c.ZCONTACTJID IN (SELECT jid FROM certified)
    """,
    (APPLE_EPOCH, DAYS),
).fetchall()

path_hits = defaultdict(int)
path_len = defaultdict(int)
path_example = {}
recovered = 0
body_found = 0
top_level = defaultdict(int)
for _pk, blob in rows:
    if not blob:
        continue
    try:
        for f, _w, _v in parse(blob):
            top_level[f] += 1
    except ValueError:
        top_level["unparseable"] += 1
    texts = list(strings(blob))
    seen = set()
    for p, t in texts:
        if p in seen:
            continue
        seen.add(p)
        path_hits[p] += 1
        path_len[p] += len(t)
        path_example.setdefault(p, t)
    if any(len(t) >= 20 and re.search(r"[A-Za-z]{3}", t) for _p, t in texts):
        recovered += 1
    if any(p == "24.1.6" for p, _t in texts):
        body_found += 1

print(f"type-19 messages from certified-business chats, last {DAYS}d: {len(rows)}")
print(f"with >=20 chars of readable text recovered: {recovered}")
print(f"with body at 24.1.6: {body_found}")
print("top-level fields:", dict(top_level))
print("\npath | messages | avg chars | masked preview")
for p in sorted(path_hits, key=lambda k: -path_hits[k]):
    print(f"{p:<20} | {path_hits[p]:>3} | {path_len[p] // path_hits[p]:>4} | {mask(path_example[p])}")
