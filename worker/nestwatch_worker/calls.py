"""Escalation calls (CLUADE.md "Escalation call"). Two providers behind one interface:

  SimulatedCalls  the default: nothing is dialled; the outcome is scripted (SIM_CALL_OUTCOME) so the flows can be shown
  TwilioCalls     Cartesia speaks the message, Twilio dials the backup and listens for one key press

Real calls need CALLS_ENABLED=true and every Twilio and Cartesia setting; anything missing means simulated.
Cartesia gets only the message text (no names, no images); Twilio gets only the phone number and the audio link.
"""
import asyncio
import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
from typing import Awaitable, Callable
from xml.sax.saxutils import escape, quoteattr

import httpx

from .ai import EVENT_WORDS

log = logging.getLogger("nestwatch.calls")
E164 = re.compile(r"^\+[1-9]\d{7,14}$")

OnResult = Callable[[str, str], Awaitable[None]]     # (job_id, "ringing" | "pressed_1" | "no_answer" | "failed")


def _why(r: httpx.Response) -> str:
    """The provider's own reason for a refusal (Twilio: code and message), so the log says what to fix."""
    try:
        body = r.json()
        return f"{r.status_code} {body.get('code', '')} {body.get('message') or body.get('error') or body}".strip()[:300]
    except Exception:
        return f"{r.status_code} {r.text[:200]}"


class NotRetryable(Exception):
    """The call may already have been placed (for example the request to the provider timed out): do not dial again."""


def call_message(alert: dict, zone_name: str | None, now: float) -> str:
    """'A child entered the stairs area 20 seconds ago. Press 1 if you're on it.' No names, no track numbers."""
    place = f"the {zone_name} area" if zone_name else "the room"
    ago = max(0, int(now - alert["createdAt"]))
    what = {
        "zone_entry": f"A child entered {place}", "zone_entry_predicted": f"A child was heading into {place}",
        "fall": f"A possible fall was seen near {place}", "unsupervised": "A child has been without an adult nearby",
    }.get(alert["eventType"], f"A child is {EVENT_WORDS.get(alert['eventType'], 'flagged near')} {place}")
    return f"This is NestWatch. {what} {ago} seconds ago and nobody has answered yet. Press 1 if you're on it."


def twilio_signature(auth_token: str, url: str, params: dict) -> str:
    """Twilio's request signature: base64(HMAC-SHA1(auth token, url + each POST key and value, keys sorted))."""
    data = url + "".join(k + v for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def valid_twilio_signature(auth_token: str, url: str, params: dict, signature: str | None) -> bool:
    if not auth_token or not signature:
        return False
    return hmac.compare_digest(twilio_signature(auth_token, url, params), signature)


class SimulatedCalls:
    """Nothing is dialled. 'press1' answers and presses 1 after the ring time; 'no_answer' gives up after it;
    'error' fails to place the call (for the call-failure drill)."""
    name = "simulated"

    def __init__(self, outcome: str = "no_answer", ring_s: float = 6.0):
        self.outcome, self.ring_s = outcome, ring_s
        self._tasks: dict[str, asyncio.Task] = {}
        self.placed: list[tuple[str, str, str]] = []   # (job_id, phone_last4, text), for tests and /health

    async def place(self, job_id: str, phone: str, text: str, on_result: OnResult) -> str:
        if self.outcome == "error":
            raise RuntimeError("simulated provider error")
        self.placed.append((job_id, phone[-4:], text))
        log.info("SIMULATED call for %s to ...%s: %s", job_id, phone[-4:], text)

        async def script():
            await asyncio.sleep(self.ring_s)
            await on_result(job_id, "pressed_1" if self.outcome == "press1" else "no_answer")
        self._tasks[job_id] = asyncio.create_task(script())
        return f"sim_{job_id}"

    async def hang_up(self, job_id: str, call_id: str) -> None:
        task = self._tasks.pop(job_id, None)
        if task:
            task.cancel()


class TwilioCalls:
    """Speech from Cartesia (served to Twilio at /audio/<token>), the call from Twilio's REST API, results via webhooks."""
    name = "twilio"

    def __init__(self, s, http: httpx.AsyncClient | None = None):
        self.s = s
        self.http = http or httpx.AsyncClient(timeout=15.0)
        self.audio: dict[str, tuple[float, bytes]] = {}       # token -> (expires_at, wav)
        self.token_job: dict[str, str] = {}                   # one-time token (in the addresses we gave Twilio) -> job id
        self._trial: bool | None = None
        self._watchers: dict[str, asyncio.Task] = {}

    @property
    def _auth(self):
        return (self.s.twilio_sid, self.s.twilio_token)

    async def _is_trial(self) -> bool:
        """Trial accounts may only use a few call parameters (To, From, Url), and cannot receive status callbacks."""
        if self._trial is None:
            try:
                r = await self.http.get(f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_sid}.json", auth=self._auth)
                self._trial = r.status_code != 200 or r.json().get("type", "Trial") == "Trial"      # unsure: assume the stricter one
            except httpx.HTTPError:
                return True                                                                         # try again next time
        return self._trial

    async def speech(self, text: str) -> bytes:
        r = await self.http.post("https://api.cartesia.ai/tts/bytes",
                                 headers={"Authorization": f"Bearer {self.s.cartesia_key}", "Cartesia-Version": self.s.cartesia_version},
                                 json={"model_id": self.s.cartesia_model, "transcript": text,
                                       "voice": self.s.cartesia_voice,
                                       "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000}})
        if r.status_code >= 400:
            raise RuntimeError(f"cartesia refused the speech: {_why(r)}")
        return r.content

    def audio_for(self, token: str) -> bytes | None:
        now = time.time()
        for k in [k for k, (exp, _) in self.audio.items() if exp < now]:
            del self.audio[k]
            self.token_job.pop(k, None)
        item = self.audio.get(token)
        return item[1] if item else None

    def twiml(self, job_id: str, audio_token: str) -> str:
        base = self.s.public_base_url
        gather = quoteattr(f"{base}/twilio/gather?job={job_id}&t={audio_token}")
        play = escape(f"{base}/audio/{audio_token}")
        return (f'<?xml version="1.0" encoding="UTF-8"?><Response><Gather numDigits="1" timeout="10" action={gather} '
                f'method="POST"><Play>{play}</Play><Play>{play}</Play></Gather><Hangup/></Response>')

    async def place(self, job_id: str, phone: str, text: str, on_result: OnResult) -> str:
        if not E164.match(phone):
            raise ValueError("the backup's phone number is not in +E.164 form")
        wav = await self.speech(text)
        token = secrets.token_urlsafe(24)
        self.audio[token] = (time.time() + 900, wav)
        self.token_job[token] = job_id
        base = self.s.public_base_url
        # Twilio fetches the call instructions from our /twilio/voice (play the message, wait for one key). Passing the
        # instructions inline (Twiml) is refused on trial accounts.
        form = {"To": phone, "From": self.s.twilio_from, "Url": f"{base}/twilio/voice?job={job_id}&t={token}"}
        if not await self._is_trial():
            form.update({"Timeout": "25", "StatusCallback": f"{base}/twilio/status?job={job_id}", "StatusCallbackMethod": "POST",
                         "StatusCallbackEvent": ["ringing", "answered", "completed"]})
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_sid}/Calls.json"
        try:
            r = await self.http.post(url, data=form, auth=self._auth)
        except httpx.TimeoutException as e:      # the call may exist already; dialling again could ring twice
            raise NotRetryable(f"twilio timed out: {e}") from e
        if r.status_code >= 400:
            raise RuntimeError(f"twilio refused the call: {_why(r)}")
        sid = r.json()["sid"]
        self._watchers[job_id] = asyncio.create_task(self._watch(job_id, sid, on_result))
        return sid

    async def call_is_ours(self, call_sid: str) -> bool:
        """Ask Twilio whether this call really is one we placed from our number (an outbound call on our account)."""
        if not re.fullmatch(r"CA[0-9a-f]{32}", call_sid or ""):
            return False
        try:
            r = await self.http.get(f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_sid}/Calls/{call_sid}.json", auth=self._auth)
        except httpx.HTTPError:
            return False
        if r.status_code != 200:
            return False
        c = r.json()
        return c.get("from") == self.s.twilio_from and str(c.get("direction", "")).startswith("outbound")

    async def _watch(self, job_id: str, sid: str, on_result: OnResult, every: float = 2.0, ring_limit: float = 40.0,
                     give_up: float = 150.0) -> None:
        """Ask Twilio how the call is going until it ends. Webhooks need a paid account for status events, and a call
        nobody picks up would otherwise sit 'ringing' for Twilio's default minute."""
        started, url = time.time(), f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_sid}/Calls/{sid}.json"
        try:
            while time.time() - started < give_up:
                await asyncio.sleep(every)
                try:
                    r = await self.http.get(url, auth=self._auth)
                except httpx.HTTPError:
                    continue
                status = r.json().get("status", "") if r.status_code == 200 else ""
                if status in ("queued", "ringing") and time.time() - started > ring_limit:
                    await self.hang_up(job_id, sid, keep_watcher=True)                 # nobody picked up
                    await on_result(job_id, "no_answer")
                    return
                outcome = twilio_outcome(status)
                if outcome and outcome != "ringing":
                    await on_result(job_id, outcome)
                    return
            await on_result(job_id, "no_answer")
        except asyncio.CancelledError:
            raise
        finally:
            self._watchers.pop(job_id, None)

    async def hang_up(self, job_id: str, call_id: str, keep_watcher: bool = False) -> None:
        watcher = None if keep_watcher else self._watchers.pop(job_id, None)
        if watcher:
            watcher.cancel()
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_sid}/Calls/{call_id}.json"
        try:
            await self.http.post(url, data={"Status": "completed"}, auth=self._auth)
        except httpx.HTTPError as e:
            log.warning("could not hang up %s: %s", call_id, e)


def twilio_outcome(call_status: str) -> str | None:
    """Twilio CallStatus to our result. A pick-up is not an acknowledgement: only pressing 1 is."""
    if call_status == "ringing":
        return "ringing"
    if call_status in ("busy", "no-answer", "failed", "canceled", "completed"):
        return "no_answer"
    return None
