"""Place ONE real test call through the whole flow, and clean up afterwards.

    .venv/bin/python scripts/test_call.py                asks for Enter first, then rings the backup caregiver within seconds
    .venv/bin/python scripts/test_call.py --yes          no question
    .venv/bin/python scripts/test_call.py --wait-timer   the realistic path: wait the full 20 s for Spacetime's own timer

What happens: a test alert is raised and escalated at once (the admin-only `escalate_now`, run with the spacetime command line
tool), the worker places the call to the BACKUP caregiver (Bob by default) and the phone rings. Answer, listen, press 1.
The script then closes the alert. If nobody presses 1 within 35 s of the escalation it acknowledges the alert itself, so the
phone is not rung a second time. Without the spacetime tool, or with --wait-timer, it waits for the 20 s timer instead.
Needs: Spacetime, the worker (started with CALLS_ENABLED=true and the Twilio and Cartesia settings) and the ngrok tunnel.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flows

WORKER = flows.WORKER

try:
    health = httpx.get(f"{WORKER}/health", timeout=3).json()
except httpx.HTTPError:
    sys.exit("The worker is not running. Start it first (see the steps in the README).")
if health.get("calls") != "twilio":
    sys.exit(f"The worker is in '{health.get('calls')}' mode, so no real call would be placed. Check CALLS_ENABLED and the Twilio and "
             "Cartesia settings in worker/.env, then restart the worker.")

rows = flows.sql("SELECT id, name, role, on_duty FROM caregiver WHERE role = 'backup' AND on_duty = true")
tok = open(Path(__file__).resolve().parent.parent / ".worker-token").read().strip()
phones = {i: p for i, p in httpx.post(f"{flows.STDB}/v1/database/{flows.DB}/sql", headers={"Authorization": f"Bearer {tok}"},
                                      content="SELECT caregiver_id, phone FROM worker_contacts").json()[0]["rows"]}
if not rows:
    sys.exit("No backup caregiver is on duty, so nobody would be called.")
who = rows[0]
print(f"This will ring {who['name']} (the backup caregiver) on the number ending {phones[who['id']][-4:]}.")
if "--yes" not in sys.argv:
    input("Press Enter to place the call, or Ctrl+C to cancel. ")



def escalate_now(alert_id: str) -> bool:
    """Skip the 20 s timer. Needs the spacetime tool logged in as the admin (the identity that published the module)."""
    cli = os.environ.get("SPACETIME") or shutil.which("spacetime")
    if not cli:
        return False
    r = subprocess.run([cli, "call", "--no-config", flows.DB, "escalate_now", json.dumps(alert_id), "--server", "local"],
                       capture_output=True, text=True)
    return r.returncode == 0


aid, clip = flows.open_alert("t7")
frame = Path(__file__).resolve().parent / "test_frame.jpg"      # so the text message carries an image
httpx.post(f"{WORKER}/keyframes", data={"clip_ref": clip}, files=[("frames", ("f.jpg", frame.read_bytes(), "image/jpeg"))],
           headers={"Authorization": f"Bearer {flows.VISION}"}).raise_for_status()
fast = "--wait-timer" not in sys.argv and escalate_now(aid)
t0, esc_at, last, result = time.time(), None, None, "nobody pressed 1 in time"
try:
    print("The phone should ring in a few seconds." if fast else "The phone should ring in about 25 seconds (waiting for the 20 s timer).",
          "Answer it and press 1 when you hear the message.", flush=True)
    while time.time() - t0 < 120:
        s = flows.status(aid)
        jobs = flows.sql(f"SELECT id, attempt, status FROM call_job WHERE alert_id = '{aid}'")
        state = (s["status"], tuple((j["attempt"], j["status"]) for j in jobs))
        if state != last:
            print(f"  {time.time() - t0:5.1f} s  alert={s['status']:10s} calls={[(j['attempt'], j['status']) for j in jobs]}", flush=True)
            last = state
        if s["status"] == "escalated" and esc_at is None:
            esc_at = time.time()
        if s["acked_via"] == [0, "phone_call"]:
            result = "SUCCESS: you pressed 1 and the alert was acknowledged by phone"
            break
        if esc_at and time.time() - esc_at > 35:
            result = "nobody pressed 1 within 35 s (stopped here so the phone is not rung a second time)"
            break
        time.sleep(0.5)
finally:
    if flows.status(aid)["status"] not in ("owned", "closed", "reported"):
        flows.call(flows.VISION, "acknowledge_alert", [aid, "c_maria", "buzzer"])     # cancels any further call
    if flows.status(aid)["status"] == "owned":
        flows.close(aid, "Test call finished")
print("RESULT:", result)
