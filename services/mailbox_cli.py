#!/usr/bin/python3
"""An authenticated local mailbox CLI for exercising the real provisioning contract."""
import json
import os
import sys
import urllib.request
from pathlib import Path

if "--version" in sys.argv:
    print("ciab-mailbox 1")
    raise SystemExit(0)
try:
    state = json.loads(Path(os.environ["CIAB_MAILBOX_HOME"], "auth.json").read_text())
    request = urllib.request.Request(state["url"] + "/mail", headers={"Authorization": "Bearer " + state["token"]})
    with urllib.request.urlopen(request, timeout=10) as response:
        messages = json.load(response)
    print(json.dumps({"messages": len(messages)}))
except Exception:
    print("Mailbox access failed; reprovision the local service authentication.", file=sys.stderr)
    raise SystemExit(2)
