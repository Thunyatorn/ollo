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

    async def speech(self, text: str) -> bytes:
        r = await self.http.post("https://api.cartesia.ai/tts/bytes",
                                 headers={"Authorization": f"Bearer {self.s.cartesia_key}", "Cartesia-Version": self.s.cartesia_version},
                                 json={"model_id": self.s.cartesia_model, "transcript": text,
                                       "voice": self.s.cartesia_voice,
                                       "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 24000}})
        r.raise_for_status()
        return r.content

    def audio_for(self, token: str) -> bytes | None:
        now = time.time()
        for k in [k for k, (exp, _) in self.audio.items() if exp < now]:
            del self.audio[k]
        item = self.audio.get(token)
        return item[1] if item else None

    def twiml(self, job_id: str, audio_token: str) -> str:
        base = self.s.public_base_url
        gather = quoteattr(f"{base}/twilio/gather?job={job_id}")
        play = escape(f"{base}/audio/{audio_token}")
        return (f'<?xml version="1.0" encoding="UTF-8"?><Response><Gather numDigits="1" timeout="10" action={gather} '
                f'method="POST"><Play>{play}</Play><Play>{play}</Play></Gather><Hangup/></Response>')

    async def place(self, job_id: str, phone: str, text: str, on_result: OnResult) -> str:
        if not E164.match(phone):
            raise ValueError("the backup's phone number is not in +E.164 form")
        wav = await self.speech(text)
        token = secrets.token_urlsafe(24)
        self.audio[token] = (time.time() + 900, wav)
        base = self.s.public_base_url
        form = {"To": phone, "From": self.s.twilio_from, "Twiml": self.twiml(job_id, token), "Timeout": "25",
                "StatusCallback": f"{base}/twilio/status?job={job_id}", "StatusCallbackMethod": "POST",
                "StatusCallbackEvent": ["ringing", "answered", "completed"]}
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_sid}/Calls.json"
        try:
            r = await self.http.post(url, data=form, auth=(self.s.twilio_sid, self.s.twilio_token))
        except httpx.TimeoutException as e:      # the call may exist already; dialling again could ring twice
            raise NotRetryable(f"twilio timed out: {e}") from e
        r.raise_for_status()
        return r.json()["sid"]

    async def hang_up(self, job_id: str, call_id: str) -> None:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.s.twilio_sid}/Calls/{call_id}.json"
        try:
            await self.http.post(url, data={"Status": "completed"}, auth=(self.s.twilio_sid, self.s.twilio_token))
        except httpx.HTTPError as e:
            log.warning("could not hang up %s: %s", call_id, e)


def twilio_outcome(call_status: str) -> str | None:
    """Twilio CallStatus to our result. A pick-up is not an acknowledgement: only pressing 1 is."""
    if call_status == "ringing":
        return "ringing"
    if call_status in ("busy", "no-answer", "failed", "canceled", "completed"):
        return "no_answer"
    return None
