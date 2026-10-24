"""Drive the end-to-end flows (CLUADE.md "End-to-end flows") against a LOCAL stack, playing the vision service and a
caregiver's phone, and check what Spacetime and the worker did. Nothing real is dialled: run the worker with simulated
calls. Every alert this script opens is acknowledged and closed again.

  .venv/bin/python scripts/flows.py primary        flow 1: buzzer tap, close, report
  .venv/bin/python scripts/flows.py escalation     flow 2: nobody taps, backup call (worker: SIM_CALL_OUTCOME=press1)
  .venv/bin/python scripts/flows.py rule           flow 3: plain-language rule, confirm, then turned off again
  .venv/bin/python scripts/flows.py opinion        flow 4: medium alert with key frames (lowering needs Claude on)
  .venv/bin/python scripts/flows.py call-failure   drill: calls fail (worker: SIM_CALL_OUTCOME=error) -> unanswered
  .venv/bin/python scripts/flows.py worker-down    drill: start with the worker STOPPED; this script starts it later
For the local-alarm checks, run the vision service too (any clip, e.g. an empty room, with --quiet-alarm).
"""
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
STDB, DB, WORKER, VISION_API = "http://127.0.0.1:3000", "nestwatch-test", "http://127.0.0.1:8787", "http://127.0.0.1:8000"
VISION = (ROOT / "tools/.vision-token").read_text().strip()
TMP = Path(__file__).resolve().parent.parent / ".flows-caregiver-token"       # git-ignored via worker/.flows-*
NONE = {"none": []}


def call(token, reducer, args):
    r = httpx.post(f"{STDB}/v1/database/{DB}/call/{reducer}", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, content=json.dumps(args))
    if r.status_code != 200:
        raise RuntimeError(f"{reducer}: {r.status_code} {r.text[:200]}")


def sql(q, token=VISION):
    r = httpx.post(f"{STDB}/v1/database/{DB}/sql", headers={"Authorization": f"Bearer {token}"}, content=q)
    r.raise_for_status()
    res = r.json()[0]
    names = [e["name"]["some"] for e in res["schema"]["elements"]]
    return [dict(zip(names, row)) for row in res["rows"]]


def caregiver_token() -> str:
    """A test device signed in as Maria (several devices may claim one caregiver)."""
    if TMP.exists():
        return TMP.read_text().strip()
    d = httpx.post(f"{STDB}/v1/identity").json()
    call(d["token"], "claim_caregiver", ["c_maria", "maria"])
    TMP.write_text(d["token"])
    TMP.chmod(0o600)
    return d["token"]


def wait_for(what, check, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = check()
        if v:
            print(f"  {time.time() - t0:5.1f} s  {what}")
            return v
        time.sleep(0.25)
    raise SystemExit(f"FAIL: {what} did not happen within {timeout:.0f} s")


def open_alert(track, event="zone_entry_predicted", zone="z_1", severity="high"):
    track = f"{track}{int(time.time()) % 10000:04d}"       # a fresh track each run: an open alert is reused per track and zone
    clip = f"evt_{int(time.time())}_{track}"
    call(VISION, "report_event", [track, event, zone, severity, {"some": 2.8} if event == "zone_entry_predicted" else NONE, clip])
    a = wait_for("alert created", lambda: [r for r in sql(f"SELECT id, status FROM alert WHERE clip_ref = '{clip}'")], 5)[0]
    print(f"           {a['id']} {severity} {event}")
    return a["id"], clip


def status(aid):
    return sql(f"SELECT status, acked_via, severity FROM alert WHERE id = '{aid}'")[0]


def report_for(aid):
    def found():
        if status(aid)["status"] != "reported":
            return None
        return [r for r in sql("SELECT alert_id, summary, lines FROM report WHERE kind = 'incident'") if r["alert_id"] == [0, aid]]
    return wait_for("report written by the worker", found, 120)[0]


def close(aid, reason):
    call(VISION, "close_alert", [aid, reason])


def primary():
    aid, _ = open_alert("t41")
    call(VISION, "acknowledge_alert", [aid, "c_maria", "buzzer"])
    wait_for("owned via buzzer", lambda: status(aid)["status"] == "owned", 5)
    close(aid, "Child back in the play area")
    r = report_for(aid)
    print("  report:", r["summary"][:120], f"({len(r['lines'])} lines)")


def escalation():
    aid, _ = open_alert("t42")
    wait_for("escalated after 20 s, call queued", lambda: status(aid)["status"] == "escalated", 30)
    wait_for("acknowledged by the backup's key press", lambda: status(aid)["acked_via"] == [0, "phone_call"], 30)
    jobs = sql(f"SELECT id, status FROM call_job WHERE alert_id = '{aid}'")
    print("  call jobs:", jobs)
    assert any(j["status"] == "answered" for j in jobs), "the answered call should be recorded"
    close(aid, "Backup checked the stairs")
    report_for(aid)


def call_failure():
    aid, _ = open_alert("t43")
    wait_for("escalated", lambda: status(aid)["status"] == "escalated", 30)
    wait_for("first call recorded as failed", lambda: any(j["status"] == "failed" for j in sql(f"SELECT status FROM call_job WHERE alert_id = '{aid}'")), 40)
    wait_for("unanswered as soon as the call failed (local alarm + all staff)", lambda: status(aid)["status"] == "unanswered", 10)
    print("  call jobs:", sql(f"SELECT id, attempt, status FROM call_job WHERE alert_id = '{aid}'"))
    try:                                                  # the vision service, if running, sounds the alarm on its next poll
        wait_for("local alarm on the vision computer", lambda: f"unanswered:{aid}" in httpx.get(f"{VISION_API}/health").json()["alarm"]["reasons"], 5)
    except httpx.HTTPError:
        print("  (vision service not running: alarm not checked)")
    call(VISION, "acknowledge_alert", [aid, "c_maria", "buzzer"])
    close(aid, "Drill over")
    report_for(aid)


def worker_down():
    import os
    import subprocess
    if _up(WORKER):
        raise SystemExit("stop the worker first")
    aid, _ = open_alert("t61")
    wait_for("escalated by Spacetime's own timer (no worker)", lambda: status(aid)["status"] == "escalated", 30)
    wait_for("unanswered by the second timer", lambda: status(aid)["status"] == "unanswered", 40)
    if _up(VISION_API):
        wait_for("local alarm on the vision computer", lambda: f"unanswered:{aid}" in httpx.get(f"{VISION_API}/health").json()["alarm"]["reasons"], 5)
    print("  calls waiting:", sql(f"SELECT id, attempt, status FROM call_job WHERE alert_id = '{aid}'"))
    env = dict(os.environ, SIM_CALL_OUTCOME="press1", SIM_RING_S="3")
    subprocess.Popen([sys.executable, "-m", "nestwatch_worker.main"], env=env, cwd=Path(__file__).resolve().parent.parent,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    print("  worker started (press1); it keeps running afterwards")
    wait_for("backup reached once the worker is back", lambda: status(aid)["acked_via"] == [0, "phone_call"], 30)
    calls = sql(f"SELECT id, attempt, status FROM call_job WHERE alert_id = '{aid}'")
    print("  calls:", calls)
    assert sum(c["status"] == "answered" for c in calls) == 1, "only the newest waiting call should ring"
    close(aid, "Drill over")
    report_for(aid)


def _up(url) -> bool:
    try:
        httpx.get(f"{url}/health", timeout=1)
        return True
    except httpx.HTTPError:
        return False


def rule():
    tok = caregiver_token()
    r = httpx.post(f"{WORKER}/rules/interpret", headers={"Authorization": f"Bearer {tok}"},
                   json={"room_id": "main", "text": "Keep kids away from the kitchen gate during nap time."}, timeout=60)
    r.raise_for_status()
    d = r.json()
    print("  draft:", d)
    zid = d["zone_draft_id"]
    assert zid and sql(f"SELECT status FROM zone WHERE id = '{zid}'")[0]["status"] == "draft"
    call(tok, "confirm_zone", [zid])
    wait_for("rule confirmed and active", lambda: sql(f"SELECT status FROM zone WHERE id = '{zid}'")[0]["status"] == "active", 5)
    z = sql(f"SELECT name, severity, schedule, escalation FROM zone WHERE id = '{zid}'")[0]
    call(tok, "update_zone", [zid, z["name"], z["severity"], z["schedule"], z["escalation"], "off"])     # tidy up: leave it off
    print("  turned the test rule off again")
    bad = httpx.post(f"{WORKER}/rules/interpret", json={"room_id": "main", "text": "x"})
    assert bad.status_code == 401, "no token must be refused"


def opinion():
    aid, clip = open_alert("t44", event="unsupervised", zone="", severity="medium")
    saved = sorted((ROOT / "vision/evidence/keyframes").glob("*.jpg"))[-2:]      # real, already-blurred key frames
    if not saved:
        raise SystemExit("run the vision service once first: no blurred key frames under vision/evidence/keyframes")
    r = httpx.post(f"{WORKER}/keyframes", headers={"Authorization": f"Bearer {VISION}"}, data={"clip_ref": clip},
                   files=[("frames", (p.name, p.read_bytes(), "image/jpeg")) for p in saved])
    print("  key frames:", r.status_code, r.json())
    time.sleep(8)
    s = status(aid)
    print("  after the second opinion window:", s)
    call(VISION, "acknowledge_alert", [aid, "c_maria", "buzzer"])
    close(aid, "Adult was nearby")
    report_for(aid)


if __name__ == "__main__":
    {"primary": primary, "escalation": escalation, "rule": rule, "opinion": opinion, "call-failure": call_failure, "worker-down": worker_down}[sys.argv[1]]()
    print("PASS")
