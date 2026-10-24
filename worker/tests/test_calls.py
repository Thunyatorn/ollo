import json
from urllib.parse import parse_qs

import httpx
import pytest

from nestwatch_worker.calls import (NotRetryable, TwilioCalls, call_message, twilio_outcome, twilio_signature,
                                    valid_twilio_signature)


def test_message_has_place_and_time_but_no_names_or_tracks():
    alert = {"eventType": "zone_entry", "trackId": "t4", "createdAt": 1000.0}
    text = call_message(alert, "stairs", now=1020.4)
    assert text == "This is NestWatch. A child entered the stairs area 20 seconds ago and nobody has answered yet. Press 1 if you're on it."
    assert "t4" not in text and "4" not in text.replace("1 if", "")


def test_signature_matches_twilios_own_validator():
    from twilio.request_validator import RequestValidator
    url = "https://worker.example.test/twilio/gather?job=call_7"
    params = {"CallSid": "CA123", "Digits": "1", "From": "+15550000001", "To": "+15550000002"}
    sig = RequestValidator("secret-token").compute_signature(url, params)
    assert twilio_signature("secret-token", url, params) == sig
    assert valid_twilio_signature("secret-token", url, params, sig)
    assert not valid_twilio_signature("secret-token", url, {**params, "Digits": "2"}, sig)
    assert not valid_twilio_signature("", url, params, sig) and not valid_twilio_signature("secret-token", url, params, None)


@pytest.mark.parametrize("status,outcome", [("ringing", "ringing"), ("in-progress", None), ("completed", "no_answer"),
                                            ("busy", "no_answer"), ("no-answer", "no_answer"), ("failed", "no_answer")])
def test_twilio_outcome(status, outcome):
    assert twilio_outcome(status) == outcome          # a pick-up alone never acknowledges


def make_twilio(settings, handler):
    settings.twilio_sid, settings.twilio_token, settings.twilio_from = "AC1", "tok", "+15550009999"
    settings.cartesia_key, settings.cartesia_voice = "sk_car_test", "voice-1"
    return TwilioCalls(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_twilio_place_speaks_then_dials(settings):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        if req.url.host == "api.cartesia.ai":
            return httpx.Response(200, content=b"RIFFwav")
        return httpx.Response(201, json={"sid": "CA42"})

    calls = make_twilio(settings, handler)
    sid = await calls.place("call_7", "+15550000002", "Press 1 if you're on it.", on_result=None)
    assert sid == "CA42"
    tts, dial = seen
    body = json.loads(tts.content)
    assert tts.headers["authorization"] == "Bearer sk_car_test" and tts.headers["cartesia-version"] == "2026-08-14"
    assert body["voice"] == "voice-1" and body["model_id"] == "sonic-3.6" and body["transcript"] == "Press 1 if you're on it."
    form = parse_qs(dial.content.decode())
    assert dial.url.path == "/2010-04-01/Accounts/AC1/Calls.json" and form["To"] == ["+15550000002"]
    assert form["StatusCallbackEvent"] == ["ringing", "answered", "completed"]
    assert "https://worker.example.test/twilio/gather?job=call_7" in form["Twiml"][0]
    token = form["Twiml"][0].split("/audio/")[1].split("<")[0]
    assert calls.audio_for(token) == b"RIFFwav" and calls.audio_for("guess") is None


async def test_twilio_timeout_is_not_retried_and_bad_numbers_refused(settings):
    def handler(req):
        if req.url.host == "api.cartesia.ai":
            return httpx.Response(200, content=b"RIFF")
        raise httpx.ReadTimeout("slow", request=req)

    calls = make_twilio(settings, handler)
    with pytest.raises(NotRetryable):
        await calls.place("call_7", "+15550000002", "hi", on_result=None)
    with pytest.raises(ValueError):
        await calls.place("call_7", "555-0002", "hi", on_result=None)
