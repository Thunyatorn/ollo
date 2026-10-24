import json
from urllib.parse import parse_qs

import httpx
import pytest

from nestwatch_worker.calls import (NotRetryable, TwilioCalls, call_message, twilio_outcome, twilio_signature,
                                    valid_twilio_signature)


def test_message_has_place_and_time_but_no_names_or_tracks():
    alert = {"eventType": "zone_entry", "trackId": "t4", "createdAt": 1000.0}
    text = call_message(alert, "stairs", now=1020.4)
    assert text == "This is ollo. A child entered the stairs area 20 seconds ago and nobody has answered yet. Press 1 if you're on it."
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


def twilio_handler(account_type="Trial", seen=None, call_statuses=()):
    """A pretend Cartesia and Twilio. call_statuses: what GET .../Calls/CA42 answers, one per request, then the last again."""
    statuses = list(call_statuses)

    def handler(req: httpx.Request):
        if seen is not None:
            seen.append(req)
        if req.url.host == "api.cartesia.ai":
            return httpx.Response(200, content=b"RIFFwav")
        path = req.url.path
        if req.method == "POST" and path.endswith("/Calls.json"):
            return httpx.Response(201, json={"sid": "CA42"})
        if req.method == "GET" and path.endswith("/Calls/CA42.json"):
            return httpx.Response(200, json={"status": statuses.pop(0) if len(statuses) > 1 else (statuses[0] if statuses else "ringing")})
        if req.method == "POST" and path.endswith("/Calls/CA42.json"):
            return httpx.Response(200, json={"status": "completed"})
        return httpx.Response(200, json={"type": account_type})                       # GET .../Accounts/AC1.json
    return handler


def stop_watchers(calls):
    for t in calls._watchers.values():
        t.cancel()


async def test_twilio_place_speaks_then_dials_with_a_url_not_inline_instructions(settings):
    seen = []
    calls = make_twilio(settings, twilio_handler("Trial", seen))
    sid = await calls.place("call_7", "+15550000002", "Press 1 if you're on it.", on_result=None)
    stop_watchers(calls)
    assert sid == "CA42"
    tts = next(r for r in seen if r.url.host == "api.cartesia.ai")
    body = json.loads(tts.content)
    assert tts.headers["authorization"] == "Bearer sk_car_test" and tts.headers["cartesia-version"] == "2026-08-14"
    assert body["voice"] == "voice-1" and body["model_id"] == "sonic-3.6" and body["transcript"] == "Press 1 if you're on it."
    dial = next(r for r in seen if r.method == "POST" and r.url.path.endswith("/Calls.json"))
    form = parse_qs(dial.content.decode())
    assert form["To"] == ["+15550000002"]
    assert set(form) == {"To", "From", "Url"}                                        # exactly what Twilio's own trial example sends
    assert form["Url"][0].startswith("https://worker.example.test/twilio/voice?job=call_7&t=")
    token = form["Url"][0].split("&t=")[1]
    assert calls.audio_for(token) == b"RIFFwav" and calls.audio_for("guess") is None
    assert "Gather" in calls.twiml("call_7", token) and f"/audio/{token}" in calls.twiml("call_7", token)


async def test_a_paid_account_also_gets_a_ring_limit_and_status_callbacks(settings):
    seen = []
    calls = make_twilio(settings, twilio_handler("Full", seen))
    await calls.place("call_7", "+15550000002", "hi", on_result=None)
    stop_watchers(calls)
    dial = next(r for r in seen if r.method == "POST" and r.url.path.endswith("/Calls.json"))
    form = parse_qs(dial.content.decode())
    assert form["Timeout"] == ["25"] and form["StatusCallbackEvent"] == ["ringing", "answered", "completed"]


async def test_watching_a_call_reports_no_answer_when_it_ends_without_a_key_press(settings):
    got = []

    async def on_result(job, outcome):
        got.append((job, outcome))
    calls = make_twilio(settings, twilio_handler(call_statuses=["ringing", "in-progress", "completed"]))
    await calls._watch("call_7", "CA42", on_result, every=0.01)
    assert got == [("call_7", "no_answer")]


async def test_watching_a_call_that_rings_too_long_hangs_up(settings):
    got, seen = [], []

    async def on_result(job, outcome):
        got.append((job, outcome))
    calls = make_twilio(settings, twilio_handler(call_statuses=["ringing"], seen=seen))
    await calls._watch("call_7", "CA42", on_result, every=0.01, ring_limit=0.05)
    assert got == [("call_7", "no_answer")]
    assert any(r.method == "POST" and r.url.path.endswith("/Calls/CA42.json") for r in seen)        # Status=completed


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


async def test_a_refusal_from_twilio_says_why(settings):
    def handler(req):
        if req.url.host == "api.cartesia.ai":
            return httpx.Response(200, content=b"RIFF")
        return httpx.Response(400, json={"code": 21608, "message": "The number is unverified. Trial accounts may only call verified numbers."})
    calls = make_twilio(settings, handler)
    with pytest.raises(RuntimeError, match="21608.*unverified"):
        await calls.place("call_7", "+15550000002", "hi", on_result=None)


async def test_a_refusal_from_cartesia_says_why(settings):
    calls = make_twilio(settings, lambda req: httpx.Response(402, json={"error": "out of credits"}))
    with pytest.raises(RuntimeError, match="cartesia.*402.*out of credits"):
        await calls.place("call_7", "+15550000002", "hi", on_result=None)
