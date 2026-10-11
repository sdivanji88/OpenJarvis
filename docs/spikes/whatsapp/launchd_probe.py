"""F-028 spike: can a launchd-launched process read WhatsApp's Group Container?

Writes only counts, timings and error strings to the result file.
"""

import os
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path.home() / "Library/Group Containers/group.net.whatsapp.WhatsApp.shared"
OUT = Path("/tmp/wa_spike/launchd_result.txt")

lines = [f"executable={sys.executable} realpath={os.path.realpath(sys.executable)}",
         f"ppid={os.getppid()} uid={os.getuid()}"]


def probe(label, fn):
    t = time.time()
    try:
        result = fn()
        lines.append(f"{label}: OK {result} ({time.time() - t:.2f}s)")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"{label}: FAIL {type(exc).__name__}: {exc} ({time.time() - t:.2f}s)")


def count(db, table):
    con = sqlite3.connect(f"file:{ROOT / db}?mode=ro", uri=True)
    try:
        return con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


probe("listdir", lambda: len(os.listdir(ROOT)))
probe("ChatStorage.ZWACHATSESSION", lambda: count("ChatStorage.sqlite", "ZWACHATSESSION"))
probe("Biz.ZWABIZVERIFIEDNAMEDATA", lambda: count("Biz/Biz.sqlite", "ZWABIZVERIFIEDNAMEDATA"))
probe("LID.ZWAPHONENUMBERLIDPAIR", lambda: count("LID.sqlite", "ZWAPHONENUMBERLIDPAIR"))
probe("ChatStorage second open", lambda: count("ChatStorage.sqlite", "ZWAMESSAGE"))
probe("TCC.db (Full Disk Access check)", lambda: sqlite3.connect(
    f"file:{Path.home() / 'Library/Application Support/com.apple.TCC/TCC.db'}?mode=ro",
    uri=True).execute("select 1").fetchone())

OUT.write_text("\n".join(lines) + "\n")
