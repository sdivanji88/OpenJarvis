#!/bin/sh
# Prints ALLOWED or BLOCKED for each URL. Runs inside a sandbox.
# Uses the sandbox venv Python, since OpenShell network rules are scoped per binary.
PY="${PROBE_PYTHON:-/sandbox/.venv/bin/python3}"
for url in "$@"; do
  if "$PY" - "$url" <<'PY' >/dev/null 2>&1
import sys, urllib.request
urllib.request.urlopen(sys.argv[1], timeout=5)
PY
  then echo "ALLOWED $url"; else echo "BLOCKED $url"; fi
done
