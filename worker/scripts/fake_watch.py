"""Act like the ollo Garmin app, to test the watch path without a watch: the same requests, through the public address.

    .venv/bin/python scripts/fake_watch.py https://<public address> CODE [--act acknowledge|decline]
"""
import json
import sys

import httpx

server, code = sys.argv[1].rstrip("/"), sys.argv[2]
h = {"X-Watch-Key": code, "ngrok-skip-browser-warning": "1"}
with httpx.Client(timeout=10, headers={"User-Agent": "Garmin-ConnectIQ-test"}) as c:
    r = c.get(f"{server}/watch/state", headers=h)
    print("GET /watch/state ->", r.status_code)
    state = r.json()
    print(json.dumps(state, indent=1)[:900])
    if "--act" in sys.argv and state.get("alerts"):
        decision = sys.argv[sys.argv.index("--act") + 1]
        a = state["alerts"][0]
        r = c.post(f"{server}/watch/act", headers={**h, "Content-Type": "application/json"}, json={"alert_id": a["id"], "decision": decision})
        print(f"POST /watch/act {decision} {a['id']} ->", r.status_code, r.json())
