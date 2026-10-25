"""The worker's main loop: watch Spacetime, start background jobs, write results back (CLUADE.md "Worker service").

  call_job queued        -> place the escalation call (retry if placing fails); press 1 acknowledges via phone_call
  call_job cancelled     -> hang up a call still ringing (someone acknowledged meanwhile)
  new medium/low alert   -> second opinion, at most 5 s, may only lower the urgency
  alert closed           -> incident report (status becomes reported)
  closing time           -> daily summary

Nothing here is on the alert path: buzzers, screens and escalation timers never wait for the worker, so a dead
worker delays reports and calls but never an alert. Spacetime's own timers escalate; the backstop below only
helps if they ever stop.
"""
import asyncio
import logging
import time
from datetime import datetime

import httpx

from . import ai
from .calls import NotRetryable, call_message, call_phrase
from .spacetime import Rejected, Spacetime, opt, quoted
from .store import KeyframeStore

log = logging.getLogger("nestwatch.worker")
OPEN_FOR_OPINION = ("open", "notified", "escalated")


class Worker:
    def __init__(self, stdb: Spacetime, settings, claude: ai.Claude | None, calls, keyframes: KeyframeStore, clock=time.time, texts=None):
        self.stdb, self.s, self.claude, self.calls, self.keyframes, self.clock = stdb, settings, claude, calls, keyframes, clock
        self.texts = texts
        self.started_at = clock()
        self.live_calls: dict[str, str | None] = {}     # job id -> provider call id, while the call is in progress
        self._job_alert: dict[str, str] = {}            # job id -> alert id
        self._call_started: set[str] = set()
        self._opinion_done: set[str] = set()
        self._report_started: dict[str, float] = {}     # alert id -> when (retried after a minute if it failed)
        self._daily_done: str | None = None
        self._zone_names: dict[str, str] = {}
        self._zones_at = self._backstop_at = self._daily_check_at = 0.0
        self._tasks: set[asyncio.Task] = set()
        self.online, self.last_poll_ok, self.poll_errors = False, None, 0
        self.stats = {"calls_placed": 0, "calls_failed": 0, "acks_by_phone": 0, "opinions": 0, "lowered": 0,
                      "opinions_late": 0, "reports": 0, "reports_plain": 0, "lines_dropped": 0, "dailies": 0}

    # ---------- plumbing ----------
    def spawn(self, coro, name: str) -> asyncio.Task:
        async def guarded():
            try:
                await coro
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job %s failed", name)
        task = asyncio.create_task(guarded(), name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def idle(self) -> None:
        """Wait for every running job (tests)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def run(self) -> None:
        while True:
            try:
                await self.poll()
                if not self.online:
                    log.info("connected to Spacetime")
                self.online, self.last_poll_ok = True, self.clock()
            except (httpx.HTTPError, Rejected) as e:
                self.poll_errors += 1
                if self.online or self.poll_errors == 1:
                    log.warning("Spacetime unreachable, will keep trying: %s", e)
                self.online = False
            await asyncio.sleep(self.s.poll_s)

    async def zone_name(self, zone_id: str) -> str | None:
        if self.clock() - self._zones_at > 10 or zone_id not in self._zone_names:
            self._zone_names = {z["id"]: z["name"] for z in await self.stdb.sql("SELECT id, name FROM zone")}
            self._zones_at = self.clock()
        return self._zone_names.get(zone_id)

    async def events(self, alert_id: str) -> list[dict]:
        return await self.stdb.sql(f"SELECT * FROM incident_event WHERE alert_id = {quoted(alert_id)}")

    async def alert(self, alert_id: str) -> dict | None:
        found = await self.stdb.sql(f"SELECT * FROM alert WHERE id = {quoted(alert_id)}")
        return found[0] if found else None

    async def job(self, job_id: str) -> dict | None:
        found = await self.stdb.sql(f"SELECT * FROM call_job WHERE id = {quoted(job_id)}")
        return found[0] if found else None

    # ---------- one poll ----------
    async def poll(self) -> None:
        now = self.clock()
        alerts = await self.stdb.sql("SELECT * FROM alert WHERE status != 'reported'")
        jobs = await self.stdb.sql("SELECT * FROM call_job WHERE status = 'queued' OR status = 'cancelled'")

        newest = {}                                             # alert id -> highest queued attempt
        for j in jobs:
            if j["status"] == "queued" and j["attempt"] > newest.get(j["alertId"], -1):
                newest[j["alertId"]] = j["attempt"]
        for j in jobs:
            if j["status"] == "queued" and j["id"] not in self._call_started and j["attempt"] < newest[j["alertId"]]:
                self._call_started.add(j["id"])                 # e.g. the worker was down: ring the backup once, not twice at once
                log.info("%s superseded by a later attempt; not dialled", j["id"])
                self.spawn(self.set_job(j["id"], "failed"), f"supersede {j['id']}")
            elif j["status"] == "queued" and j["id"] not in self._call_started:
                self._call_started.add(j["id"])
                self.spawn(self.run_call(j), f"call {j['id']}")
            elif j["status"] == "cancelled" and j["id"] in self.live_calls:
                call_id = self.live_calls.pop(j["id"])
                log.info("%s was acknowledged meanwhile; hanging up", j["id"])
                if call_id:
                    self.spawn(self.calls.hang_up(j["id"], call_id), f"hang up {j['id']}")

        for a in alerts:
            if (a["severity"] in ("medium", "low") and a["status"] in OPEN_FOR_OPINION and a["id"] not in self._opinion_done
                    and now - a["createdAt"] < 600):
                frames = self.keyframes.get(a["clipRef"])
                if frames or now - a["createdAt"] >= self.s.keyframe_wait_s:
                    self._opinion_done.add(a["id"])
                    if self.claude and frames:
                        self.spawn(self.second_opinion(a, frames), f"opinion {a['id']}")
                    elif self.claude:
                        log.info("no key frames for %s; no second opinion", a["id"])
            if a["status"] == "closed" and now - self._report_started.get(a["id"], -1e9) > 60:
                self._report_started[a["id"]] = now
                self.spawn(self.report(a), f"report {a['id']}")

        if self.s.escalation_backstop and now - self._backstop_at >= 2.0:
            self._backstop_at = now
            await self.stdb.call("escalate_due", [])

        if now - self._daily_check_at >= 30:
            self._daily_check_at = now
            await self.maybe_daily(now)

    # ---------- escalation call ----------
    async def run_call(self, job: dict) -> None:
        jid = job["id"]
        alert = await self.alert(job["alertId"])
        if not alert or alert["ownerId"]:
            return                                              # already handled; Spacetime cancels the job itself
        contact = next((c for c in await self.stdb.sql("SELECT * FROM worker_contacts") if c["caregiverId"] == job["caregiverId"]), None)
        if not contact or not contact["phone"]:
            log.error("%s: no phone number for %s", jid, job["caregiverId"])
            await self.set_job(jid, "failed")
            return
        zone = await self.zone_name(alert["zoneId"])
        text = call_message(alert, zone, self.clock())
        rooms = await self.stdb.sql("SELECT name FROM room")
        names = {c["id"]: c["name"] for c in await self.stdb.sql("SELECT id, name FROM caregiver")}
        info = {"room": rooms[0]["name"] if rooms else "the room", "alert": call_phrase(alert, zone, self.clock()),
                "caregiver": names.get(job["caregiverId"], "caregiver"), "alert_id": alert["id"], "caregiver_id": job["caregiverId"]}
        if self.texts:                                          # the text goes out beside the call, never instead of it
            frames = self.keyframes.get(alert["clipRef"])
            self.spawn(self.send_text(contact["phone"], f"ollo: {info['alert']} and nobody has answered yet.", frames[0] if frames else None),
                       f"text {jid}")
        delays = self.s.call_retry_delays_s
        self._job_alert[jid] = alert["id"]
        for older, call_id in [(j, c) for j, c in self.live_calls.items() if j != jid and self._job_alert.get(j) == alert["id"]]:
            self.live_calls.pop(older, None)                    # a newer attempt replaces one still ringing: one phone, one call
            if call_id:
                self.spawn(self.calls.hang_up(older, call_id), f"hang up {older}")
            self.spawn(self.set_job(older, "failed"), f"supersede {older}")
        for attempt in range(1 + self.s.call_retries):
            self.live_calls[jid] = None                         # results may arrive before place() returns
            try:
                self.live_calls[jid] = await self.calls.place(jid, contact["phone"], text, self.on_call_result, info)
                self.stats["calls_placed"] += 1
                await self.set_job(jid, "ringing")
                return
            except NotRetryable as e:
                log.error("%s: %s; not dialling again", jid, e)
                break
            except Exception as e:
                log.warning("%s: placing the call failed (try %d of %d): %s", jid, attempt + 1, 1 + self.s.call_retries, e)
                self.live_calls.pop(jid, None)
                if attempt < self.s.call_retries:
                    await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                    current = await self.job(jid)
                    if not current or current["status"] != "queued":
                        return                                  # acknowledged meanwhile
        self.live_calls.pop(jid, None)
        self.stats["calls_failed"] += 1
        await self.set_job(jid, "failed")                       # escalation goes on: the timer still fires, the alarm sounds

    async def send_text(self, phone: str, body: str, image: bytes | None) -> None:
        try:
            await self.texts.send(phone, body, image)
        except Exception as e:
            log.warning("could not send the text: %s", e)

    async def set_job(self, job_id: str, status: str) -> None:
        try:
            await self.stdb.call("update_call_job", [job_id, status])
        except Rejected as e:
            log.error("update_call_job %s %s refused: %s", job_id, status, e)

    async def on_call_result(self, job_id: str, outcome: str) -> None:
        """From the provider (simulated script or Twilio webhooks)."""
        if job_id not in self.live_calls or outcome == "ringing":
            return                                              # unknown, already resolved, or nothing new
        self.live_calls.pop(job_id, None)
        if outcome != "pressed_1":
            log.info("%s: no acknowledgement (%s)", job_id, outcome)
            await self.set_job(job_id, "failed")
            return
        job = await self.job(job_id)
        if not job:
            return
        await self.set_job(job_id, "answered")                  # first: the acknowledgement below cancels open jobs
        try:
            await self.stdb.call("acknowledge_alert", [job["alertId"], job["caregiverId"], "phone_call"])
            self.stats["acks_by_phone"] += 1
            log.info("%s: backup pressed 1; %s acknowledged by phone", job_id, job["alertId"])
        except Rejected as e:
            log.warning("acknowledge by phone refused (probably closed already): %s", e)

    async def on_voice_decision(self, token: str, decision: str) -> str:
        """The voice agent's tool call: the caregiver said "I'm on it" (acknowledge) or "I can't" (decline). Returns the one
        plain sentence the agent should say back. Each token works once."""
        rec = self.calls.take_token(token) if hasattr(self.calls, "take_token") else None
        if rec is None:
            return "Sorry, this call is no longer valid."
        jid, alert_id, cg = rec["job"], rec["alert"], rec["caregiver"]
        self.live_calls.pop(jid, None)
        try:
            if decision == "decline":
                await self.stdb.call("decline_alert", [alert_id, cg, "voice"])
                await self.set_job(jid, "failed")
                return "Understood. The next person is being told now. Thank you."
            await self.set_job(jid, "answered")                 # first: the acknowledgement below cancels open jobs
            await self.stdb.call("acknowledge_alert", [alert_id, cg, "voice"])
            self.stats["acks_by_voice"] = self.stats.get("acks_by_voice", 0) + 1
        except Rejected as e:
            log.warning("voice %s for %s refused: %s", decision, alert_id, e)
            return "I could not record that. Please open the ollo app."
        a = await self.alert(alert_id)
        owner = a["ownerId"] if a else None
        if owner == cg:
            return "Acknowledged. You are now responsible for this alert. Thank you."
        if owner:
            who = next((c["name"] for c in await self.stdb.sql("SELECT id, name FROM caregiver") if c["id"] == owner), "someone else")
            return f"This alert is already handled by {who}. Thank you."
        return "I could not record that. Please open the ollo app."

    # ---------- second opinion ----------
    async def second_opinion(self, alert: dict, frames: list[bytes]) -> None:
        events = await self.events(alert["id"])
        zone = await self.zone_name(alert["zoneId"])
        self.stats["opinions"] += 1
        try:
            data = await self.claude.second_opinion(alert, zone, events, frames, self.s.second_opinion_timeout_s)
        except asyncio.TimeoutError:
            self.stats["opinions_late"] += 1
            log.info("second opinion for %s was later than %.0f s; ignored", alert["id"], self.s.second_opinion_timeout_s)
            return
        verdict = ai.check_opinion(data or {}, alert["severity"])
        log.info("second opinion for %s: %s", alert["id"], (data or {}).get("verdict", "no answer"))
        if verdict:
            try:
                await self.stdb.call("set_urgency", [alert["id"], verdict["note"], verdict["lower_to"]])
                self.stats["lowered"] += 1
            except Rejected as e:
                log.info("set_urgency refused (alert changed meanwhile): %s", e)

    # ---------- incident report ----------
    async def report(self, alert: dict) -> None:
        events = await self.events(alert["id"])
        zone = await self.zone_name(alert["zoneId"])
        summary, lines = "", []
        if self.claude:
            try:
                data = await self.claude.report(alert, zone, events)
                summary, lines, dropped = ai.check_report(data or {}, events)
                self.stats["lines_dropped"] += dropped
            except Exception as e:                              # no answer from Claude: the plain report still goes out
                log.warning("Claude report for %s failed: %s", alert["id"], e)
        if not summary or not lines:
            summary, lines = ai.plain_report(alert, events, zone)
            self.stats["reports_plain"] += 1
        await self.stdb.call("save_report", [opt(alert["id"]), summary, [[l["eventId"], l["text"]] for l in lines]])
        self.stats["reports"] += 1
        log.info("report saved for %s (%d lines)", alert["id"], len(lines))

    # ---------- daily summary ----------
    async def maybe_daily(self, now: float) -> None:
        local = datetime.fromtimestamp(now)
        day = local.strftime("%Y-%m-%d")
        if self._daily_done == day or local.strftime("%H:%M") < self.s.closing_time:
            return
        dailies = await self.stdb.sql("SELECT summary FROM report WHERE kind = 'daily'")
        self._daily_done = day
        if any(r["summary"].startswith(f"Daily summary {day}") for r in dailies):
            return
        self.spawn(self.daily(day), f"daily {day}")

    async def daily(self, day: str) -> None:
        start = datetime.strptime(day, "%Y-%m-%d").timestamp()
        alerts = [a for a in await self.stdb.sql("SELECT * FROM alert") if a["createdAt"] >= start]
        ids = {a["id"] for a in alerts}
        events = [e for e in await self.stdb.sql("SELECT * FROM incident_event") if e["alertId"] in ids]
        summary, lines = "", []
        if self.claude and events:
            try:
                data = await self.claude.daily(day, events)
                summary, lines, dropped = ai.check_report(data or {}, events, max_lines=12)
                self.stats["lines_dropped"] += dropped
            except Exception as e:
                log.warning("Claude daily summary failed: %s", e)
        if not summary:
            summary, lines = ai.plain_daily(day, alerts, events)
        await self.stdb.call("save_report", [opt(None), f"Daily summary {day}: {summary}", [[l["eventId"], l["text"]] for l in lines]])
        self.stats["dailies"] += 1

    def health(self) -> dict:
        cost = {"claude_cost_usd": round(self.claude.cost_usd, 4), "claude_calls": self.claude.calls} if self.claude else {}
        return {"spacetime": "connected" if self.online else "unreachable", "last_poll_ok": self.last_poll_ok, **cost,
                "live_calls": len(self.live_calls), "running_jobs": len(self._tasks), "key_frames": len(self.keyframes),
                **self.stats}
