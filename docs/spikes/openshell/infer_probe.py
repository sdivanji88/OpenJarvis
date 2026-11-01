"""Call the OpenShell inference route from inside a sandbox (F-029 Q5).

Sends no API key: the gateway is expected to add the upstream credential.
Usage (inside a sandbox): python3 infer_probe.py [base_url]
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

base = sys.argv[1] if len(sys.argv) > 1 else "https://inference.local/v1"
body = {"model": "qwen3.5:2b", "messages": [{"role": "user", "content": "Reply with the word ok."}]}
req = urllib.request.Request(
    base + "/chat/completions",
    data=json.dumps(body).encode(),
    headers={"Content-Type": "application/json"},
)
keys = [k for k in os.environ if "KEY" in k.upper() or "TOKEN" in k.upper()]
print("env vars named *KEY*/*TOKEN*:", keys)
start = time.monotonic()
try:
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.load(resp)
    print("status", resp.status, f"{time.monotonic() - start:.1f}s")
    print("model", data.get("model"), "usage", data.get("usage"))
    print("content", (data["choices"][0]["message"].get("content") or "")[:80])
except Exception as exc:  # spike: print whatever went wrong
    print("ERROR", type(exc).__name__, str(exc)[:300])
