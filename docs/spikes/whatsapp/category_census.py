"""F-027 spike: census of the template category field (24.7) -- counts only."""

import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from decode_type19 import parse  # noqa: E402  (module runs its report on import)

ROOT = Path.home() / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared"
con = sqlite3.connect(f"file:{ROOT / 'ChatStorage.sqlite'}?mode=ro", uri=True)
con.execute(f"ATTACH 'file:{ROOT / 'Biz/Biz.sqlite'}?mode=ro' AS biz")
rows = con.execute(
    """
    WITH certified AS (
      SELECT ZJID AS jid FROM biz.ZWABIZVERIFIEDNAMEDATA
      UNION SELECT ZPHONENUMBERJID FROM biz.ZWABIZVERIFIEDNAMEDATA WHERE ZPHONENUMBERJID IS NOT NULL),
    profile AS (SELECT ZJID AS jid FROM biz.ZWABIZPROFILEDATA)
    SELECT m.ZMESSAGETYPE,
      CASE WHEN c.ZCONTACTJID IN (SELECT jid FROM certified) THEN 'certified'
           WHEN c.ZCONTACTJID IN (SELECT jid FROM profile) THEN 'profile_only'
           ELSE 'not_business' END,
      mi.ZMETADATA
    FROM ZWAMESSAGE m
    JOIN ZWACHATSESSION c ON m.ZCHATSESSION = c.Z_PK
    JOIN ZWAMEDIAITEM mi ON mi.Z_PK = m.ZMEDIAITEM
    WHERE c.ZSESSIONTYPE = 0 AND m.ZISFROMME = 0 AND mi.ZMETADATA IS NOT NULL
    """
).fetchall()

census = Counter()
for mtype, tier, blob in rows:
    category = "-"
    try:
        top = parse(blob)
        for f, w, v in top:
            if f == 24 and w == 2:
                for f2, w2, v2 in parse(v):
                    if f2 == 7 and w2 == 2:
                        category = v2.decode("utf-8", "replace")
    except ValueError:
        category = "unparseable"
    census[(mtype, tier, category)] += 1

print("\nmessage_type | sender tier | category (24.7) | messages (all time)")
for (mtype, tier, cat), n in sorted(census.items(), key=lambda kv: (kv[0][0], kv[0][1], -kv[1])):
    if cat != "-" or mtype == 19:
        print(f"{mtype:>4} | {tier:<12} | {cat:<14} | {n}")
