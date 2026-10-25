"""Family emergency actions (CLUADE.md "Family emergency actions"): an older person at home alone falls; the family gets a
Telegram message at once and, from its buttons, sends the hospital a report or calls an ambulance (stand-in number).

  fall alert            -> one Telegram message per alert: key frame, who, where, which hospital, two buttons
  "r:<alert>"           -> email the hospital: timeline + medical record + blurred fall clip (once per alert)
  "a:<alert>"           -> ask "this is a real phone call", buttons "y:<alert>" / "n:<alert>"
  "y:<alert>" (2 min)   -> one call to AMBULANCE_NUMBER with the spoken request (once per alert)

Only chats in TELEGRAM_CHAT_ID may press. Software never dials emergency services: the number must be full +E.164.
"""
import asyncio
import json
import logging
import math
import mimetypes
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

import httpx

from .calls import E164

log = logging.getLogger("nestwatch.family")
OVERPASS = "https://overpass-api.de/api/interpreter"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ollo-hackathon/1.0 (fall alerts; contact via project repo)"
CONFIRM_S = 120.0


def km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def at(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%-I:%M %p")


class Family:
    def __init__(self, s, stdb, calls, keyframes, http: httpx.AsyncClient | None = None, send_email=None, texts=None,
                 clock=time.time, sleep=asyncio.sleep):
        self.s, self.stdb, self.calls, self.keyframes, self.texts = s, stdb, calls, keyframes, texts
        self.http = http or httpx.AsyncClient(timeout=20.0)
        self.send_email = send_email or self._smtp
        self.clock, self.sleep = clock, sleep
        self.allowed = {c.strip() for c in s.telegram_chat_id.split(",") if c.strip()}
        self.started: set[str] = set()                     # chats that pressed Start (receive messages, cannot press)
        self.alerts: dict[str, dict] = {}                  # alert id -> alert, for messages announced here
        self.done: dict[tuple[str, str], float] = {}       # (alert id, "report" | "ambulance") -> when
        self.asked: dict[str, float] = {}                  # alert id -> when "call ambulance?" was asked
        self._hospital: dict | None = None
        self._offset = 0

    # ---------- Telegram ----------
    async def _api(self, method: str, **kw) -> dict:
        r = await self.http.post(f"https://api.telegram.org/bot{self.s.telegram_token}/{method}", **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"telegram refused {method}: {r.status_code} {r.text[:200]}")
        return r.json()

    async def _say(self, chat: str, text: str, buttons: list | None = None) -> None:
        body = {"chat_id": chat, "text": text}
        if buttons:
            body["reply_markup"] = {"inline_keyboard": buttons}
        await self._api("sendMessage", json=body)

    def recipients(self) -> list[str]:
        return sorted(self.allowed or self.started)

    # ---------- hospital ----------
    async def home(self) -> tuple[float, float] | None:
        if self.s.home_lat and self.s.home_lon:
            return float(self.s.home_lat), float(self.s.home_lon)
        if not self.s.home_address:
            return None
        r = await self.http.get(NOMINATIM, params={"q": self.s.home_address, "format": "json", "limit": 1},
                                headers={"User-Agent": USER_AGENT})
        found = r.json() if r.status_code == 200 else []
        if not found:
            return None
        self.s.home_lat, self.s.home_lon = found[0]["lat"], found[0]["lon"]          # geocode once
        return float(found[0]["lat"]), float(found[0]["lon"])

    async def hospital(self) -> dict:
        """Her usual hospital, else the nearest OpenStreetMap hospital with an emergency department within 25 km."""
        if self.s.hospital_name:
            return {"name": self.s.hospital_name, "address": self.s.hospital_address, "email": self.s.hospital_email,
                    "source": "usual", "distance_km": None}
        if self._hospital is not None:
            return self._hospital
        none = {"name": "", "address": "", "email": "", "source": None, "distance_km": None}
        try:
            home = await self.home()
            if not home:
                return none
            query = f'[out:json][timeout:20];nwr["amenity"="hospital"]["emergency"="yes"](around:25000,{home[0]},{home[1]});out center tags;'
            r = await self.http.post(OVERPASS, data={"data": query}, headers={"User-Agent": USER_AGENT})
            best = None
            for e in (r.json().get("elements", []) if r.status_code == 200 else []):
                lat, lon = (e.get("lat"), e.get("lon")) if "lat" in e else (e.get("center", {}).get("lat"), e.get("center", {}).get("lon"))
                tags = e.get("tags", {})
                if lat is None or not tags.get("name"):
                    continue
                d = km(home[0], home[1], lat, lon)
                if best is None or d < best["distance_km"]:
                    street = " ".join(x for x in (tags.get("addr:housenumber", ""), tags.get("addr:street", "")) if x)
                    best = {"name": tags["name"], "address": ", ".join(x for x in (street, tags.get("addr:city", "")) if x),
                            "email": tags.get("email") or tags.get("contact:email", ""), "source": "nearest", "distance_km": d}
        except (httpx.HTTPError, ValueError) as e:
            log.warning("nearest hospital lookup failed: %s", e)
            return none
        self._hospital = best or none
        return self._hospital

    @staticmethod
    def describe(h: dict) -> str:
        if not h["name"]:
            return "not found"
        return f"{h['name']} (usual)" if h["source"] == "usual" else f"{h['name']} (nearest, {h['distance_km']:.1f} km)"

    # ---------- the fall message ----------
    async def on_alert(self, alert: dict) -> None:
        if alert["id"] in self.alerts or alert.get("eventType") != "fall":
            return
        self.alerts[alert["id"]] = alert
        chats = self.recipients()
        if not chats:
            log.warning("fall %s: nobody to tell (set TELEGRAM_CHAT_ID, or press Start on the bot)", alert["id"])
            return
        frame = None
        for _ in range(6):                                  # the vision service sends key frames just after the alert
            frames = self.keyframes.get(alert.get("clipRef") or "")
            if frames:
                frame = frames[0]
                break
            await self.sleep(0.5)
        h = await self.hospital()
        name = self.s.patient_name or "Your family member"
        caption = (f"ollo: possible fall — {name} at {self.s.home_address or 'home'}, {at(alert['createdAt'])}. "
                   f"Hospital: {self.describe(h)}")
        buttons = [[{"text": "🏥 Send report to hospital", "callback_data": f"r:{alert['id']}"}],
                   [{"text": "🚑 Call ambulance", "callback_data": f"a:{alert['id']}"}]]
        for chat in chats:
            try:
                if frame:
                    await self._api("sendPhoto", data={"chat_id": chat, "caption": caption[:1000],
                                                       "reply_markup": json.dumps({"inline_keyboard": buttons})},
                                    files={"photo": ("fall.jpg", frame, "image/jpeg")})
                else:
                    await self._say(chat, caption, buttons)
            except (httpx.HTTPError, RuntimeError) as e:
                log.warning("fall %s: could not tell chat %s: %s", alert["id"], chat, e)

    # ---------- button presses ----------
    async def handle_update(self, update: dict) -> None:
        msg = update.get("message")
        if msg and str(msg.get("text", "")).startswith("/start"):
            chat = str(msg["chat"]["id"])
            self.started.add(chat)
            if self.texts is not None and hasattr(self.texts, "_chats") and chat not in self.texts._chats and not self.allowed:
                self.texts._chats.append(chat)              # the escalation text reaches it too
            await self._say(chat, f"ollo is set up for this chat. To use the emergency buttons, add {chat} to TELEGRAM_CHAT_ID.")
            return
        cb = update.get("callback_query")
        if not cb:
            return
        chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
        action, _, alert_id = str(cb.get("data", "")).partition(":")
        if chat not in self.allowed:
            await self._answer(cb, "not allowed")
            return
        alert = self.alerts.get(alert_id) or next(iter(await self.stdb.sql(f"SELECT * FROM alert WHERE id = '{alert_id}'")), None) \
            if alert_id.replace("_", "").isalnum() else None
        if not alert:
            await self._answer(cb, "This alert is no longer known.")
            return
        if action == "r":
            await self._once(cb, chat, alert, "report", self.report)
        elif action == "a":
            await self._ask_ambulance(cb, chat, alert)
        elif action == "y":
            asked = self.asked.pop(alert_id, None)
            if asked is None or self.clock() - asked > CONFIRM_S:
                await self._answer(cb, "Tap 🚑 Call ambulance again first.")
                return
            await self._once(cb, chat, alert, "ambulance", self.ambulance)
        elif action == "n":
            self.asked.pop(alert_id, None)
            await self._answer(cb, "Cancelled. No call was placed.")

    async def _answer(self, cb: dict, text: str) -> None:
        try:
            await self._api("answerCallbackQuery", data={"callback_query_id": cb["id"], "text": text})
        except (httpx.HTTPError, RuntimeError) as e:
            log.warning("could not answer a button press: %s", e)

    async def _once(self, cb, chat, alert, what, action) -> None:
        key = (alert["id"], what)
        if key in self.done:
            await self._answer(cb, f"Already done at {at(self.done[key])}.")
            return
        self.done[key] = self.clock()                      # before acting: a double tap never runs it twice
        await self._answer(cb, "Working on it…")
        try:
            result = await action(alert)
        except Exception as e:
            del self.done[key]
            log.warning("%s for %s failed: %s", what, alert["id"], e)
            await self._log(alert["id"], "family_action_failed", f"{what} failed: {e}"[:300])
            await self._say(chat, f"⚠️ Could not {'send the report' if what == 'report' else 'place the call'}: {e}")
            return
        await self._say(chat, result)

    async def _ask_ambulance(self, cb, chat, alert) -> None:
        if (alert["id"], "ambulance") in self.done:
            await self._answer(cb, f"Already called at {at(self.done[(alert['id'], 'ambulance')])}.")
            return
        number, live = self.s.ambulance_number.strip(), self.s.ambulance_live
        if (number or live) and not E164.match(number):
            await self._answer(cb, "No valid ambulance number is set.")
            await self._log(alert["id"], "family_action_failed", "ambulance: AMBULANCE_NUMBER is not a full +E.164 number")
            await self._say(chat, "⚠️ AMBULANCE_NUMBER is not a full phone number (+ and country code). "
                                  "ollo never dials emergency short codes such as 911; call them yourself.")
            return
        self.asked[alert["id"]] = self.clock()
        await self._answer(cb, "Confirm below.")
        where = self.s.home_address or "home"
        question = (f"Call the ambulance line (…{number[-4:]}) to {where}? This is a real phone call." if live else
                    f"Demo: send the ambulance request for {where}? No real call will be placed.")
        await self._say(chat, question, [[{"text": "Yes, call now" if live else "Yes (demo)", "callback_data": f"y:{alert['id']}"},
                                          {"text": "Cancel", "callback_data": f"n:{alert['id']}"}]])

    # ---------- the two actions ----------
    async def report(self, alert: dict) -> str:
        h = await self.hospital()
        to = self.s.report_to or h["email"] or self.s.hospital_fallback_email    # REPORT_TO: demo, never a hospital
        if not to:
            raise RuntimeError("no email for the hospital (set HOSPITAL_EMAIL or HOSPITAL_FALLBACK_EMAIL)")
        name = self.s.patient_name or "Patient"
        events = sorted(await self.stdb.sql(f"SELECT * FROM incident_event WHERE alert_id = '{alert['id']}'"), key=lambda e: e["at"])
        clip = await self._clip(alert.get("clipRef") or "")
        msg = EmailMessage()
        msg["From"], msg["To"] = self.s.smtp_from or self.s.smtp_user, to
        msg["Subject"] = f"ollo fall report: {name}, {at(alert['createdAt'])}"
        lines = [f"Patient: {name}", f"Home: {self.s.home_address or 'not set'}", f"Alert: possible fall at {at(alert['createdAt'])}",
                 f"Hospital: {self.describe(h)}", "", "What the camera system logged:"]
        lines += [f"  {at(e['at'])}  {e['text']}" for e in events]
        lines += ["", "Attached: the medical record" + (" and the face-blurred video of the fall." if clip else
                  ". The fall video is not available (still recording or clips are off)."),
                  "Sent by a family member through ollo. This is a camera observation, not a diagnosis."]
        msg.set_content("\n".join(lines))
        attached = []
        if self.s.medical_record_file:
            path = Path(self.s.medical_record_file)
            kind = (mimetypes.guess_type(path.name)[0] or "application/octet-stream").split("/")
            msg.add_attachment(path.read_bytes(), maintype=kind[0], subtype=kind[1], filename=path.name)
            attached.append("medical record")
        if clip:
            msg.add_attachment(clip, maintype="video", subtype="mp4", filename=f"fall-{alert['clipRef']}.mp4")
            attached.append(f"fall video ({len(clip) // 1024} KB)")
        await self.send_email(msg)
        where = (f"{to} (demo stand-in for {h['name'] or 'the hospital'})" if self.s.report_to else
                 f"{h['name']} <{to}>" if h["name"] and to == h["email"] else to)
        await self._log(alert["id"], "report_sent", f"Report sent to {where}: {', '.join(attached) or 'timeline only'}")
        return f"🏥 Report sent to {where} with {', '.join(attached) or 'the timeline only'}."

    async def _clip(self, ref: str) -> bytes | None:
        if not ref:
            return None
        for _ in range(10):                                 # up to ~20 s while the clip finishes recording
            try:
                r = await self.http.get(f"{self.s.vision_http}/clips/{ref}")
                if r.status_code == 200:
                    return r.content
            except httpx.HTTPError:
                pass
            await self.sleep(2.0)
        return None

    async def ambulance(self, alert: dict) -> str:
        number, live = self.s.ambulance_number.strip(), self.s.ambulance_live
        if live and not E164.match(number):
            raise RuntimeError("AMBULANCE_NUMBER is not a full +E.164 number")
        h = await self.hospital()
        name = self.s.patient_name or "A person"
        spoken = (f"This is ollo, an automated emergency request. {name} may have fallen at {self.s.home_address or 'her home'} "
                  f"at {at(alert['createdAt'])} and has not been confirmed safe."
                  + (f" Her usual hospital is {h['name']}." if h["source"] == "usual" else
                     f" The nearest emergency hospital is {h['name']}." if h["name"] else ""))

        if not live:                                        # AMBULANCE_LIVE is off: show the request, dial nothing
            await self._log(alert["id"], "ambulance_called", "Demo ambulance request (not dialed; AMBULANCE_LIVE is off)")
            return f"🚑 Demo: no call placed. The ambulance line would hear: \"{spoken}\""

        async def result(job_id, outcome):
            log.info("ambulance call for %s: %s", alert["id"], outcome)
        await self.calls.place(f"amb_{alert['id']}", number, spoken, result,
                               {"room": self.s.home_address or "home", "alert": "a possible fall", "caregiver": "dispatcher",
                                "alert_id": alert["id"], "caregiver_id": ""})
        await self._log(alert["id"], "ambulance_called", f"Ambulance line …{number[-4:]} called by family")
        return f"🚑 Calling the ambulance line (…{number[-4:]}) now."

    async def _log(self, alert_id: str, kind: str, text: str) -> None:
        try:
            await self.stdb.call("log_family_event", [alert_id, kind, text])
        except Exception as e:
            log.warning("could not log %s on %s: %s", kind, alert_id, e)

    # ---------- mail and the update loop ----------
    async def _smtp(self, msg: EmailMessage) -> None:
        if not self.s.smtp_host:
            raise RuntimeError("email is not set up (SMTP_HOST)")

        def send():
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(msg)
        await asyncio.to_thread(send)

    async def poll_updates(self) -> None:
        """Telegram long polling: no public address needed for the buttons."""
        while True:
            try:
                r = await self.http.post(f"https://api.telegram.org/bot{self.s.telegram_token}/getUpdates",
                                         json={"offset": self._offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]},
                                         timeout=35.0)
                for u in r.json().get("result", []) if r.status_code == 200 else []:
                    self._offset = max(self._offset, u["update_id"] + 1)
                    try:
                        await self.handle_update(u)
                    except Exception:
                        log.exception("telegram update failed")
                if r.status_code != 200:
                    await self.sleep(5.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("telegram polling: %s", e)
                await self.sleep(5.0)
