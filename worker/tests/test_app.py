import httpx

from nestwatch_worker.app import create_app
from nestwatch_worker.calls import SimulatedCalls, TwilioCalls, twilio_signature
from nestwatch_worker.jobs import Worker
from nestwatch_worker.store import KeyframeStore, TokenChecker
from tests.conftest import make_alert


def client(stdb, settings, clock, calls=None):
    kf = KeyframeStore(clock=clock)
    w = Worker(stdb, settings, None, calls or SimulatedCalls(), kf, clock=clock)
    app = create_app(w, TokenChecker(stdb), kf, settings, start_loop=False)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://worker"), w, kf


MARIA = {"authorization": "Bearer maria-token"}


async def test_rule_needs_a_signed_in_caregiver(stdb, settings, clock):
    c, *_ = client(stdb, settings, clock)
    body = {"room_id": "main", "text": "Keep kids away from the kitchen gate during nap time."}
    assert (await c.post("/rules/interpret", json=body)).status_code == 401
    assert (await c.post("/rules/interpret", json=body, headers={"authorization": "Bearer forged"})).status_code == 401
    assert (await c.post("/rules/interpret", json=body, headers={"authorization": "Bearer vision-token"})).status_code == 401


async def test_rule_becomes_an_inactive_draft(stdb, settings, clock):
    c, *_ = client(stdb, settings, clock)
    r = await c.post("/rules/interpret", json={"room_id": "main", "text": "Keep kids away from the kitchen gate during nap time."}, headers=MARIA)
    assert r.status_code == 200
    d = r.json()
    assert d["area_name"] == "Kitchen gate" and d["schedule"] == {"named": "nap_time", "start_min": None, "end_min": None}
    assert d["severity"] == "high" and d["escalation"] == "buzzer_then_call" and not d["needs_drawing"] and d["drafted_by"] == "keyword match"
    zone = next(z for z in stdb.t["zone"] if z["id"] == d["zone_draft_id"])
    assert zone["status"] == "draft"


async def test_rule_without_a_known_place_asks_for_a_drawing(stdb, settings, clock):
    c, *_ = client(stdb, settings, clock)
    d = (await c.post("/rules/interpret", json={"room_id": "main", "text": "No climbing on the radiator"}, headers=MARIA)).json()
    assert d["needs_drawing"] and d["needs"] == "drawing" and d["zone_draft_id"] is None
    assert not [z for z in stdb.t["zone"] if z["status"] == "draft"]
    bad = await c.post("/rules/interpret", json={"room_id": "main'; DROP", "text": "x"}, headers=MARIA)
    assert bad.status_code == 422


async def test_keyframes_only_from_the_vision_service(stdb, settings, clock):
    c, w, kf = client(stdb, settings, clock)
    files = [("frames", ("1.jpg", b"\xff\xd8\xff one", "image/jpeg")), ("frames", ("2.jpg", b"\xff\xd8\xff two", "image/jpeg"))]
    assert (await c.post("/keyframes", data={"clip_ref": "evt_1"}, files=files, headers=MARIA)).status_code == 401
    r = await c.post("/keyframes", data={"clip_ref": "evt_1"}, files=files, headers={"authorization": "Bearer vision-token"})
    assert r.status_code == 200 and kf.get("evt_1") == [b"\xff\xd8\xff one", b"\xff\xd8\xff two"]
    png = [("frames", ("x.png", b"\x89PNG", "image/png"))]
    assert (await c.post("/keyframes", data={"clip_ref": "evt_2"}, files=png, headers={"authorization": "Bearer vision-token"})).status_code == 422
    assert (await c.post("/keyframes", data={"clip_ref": "../x"}, files=files, headers={"authorization": "Bearer vision-token"})).status_code == 422
    clock.t += 24 * 3600
    assert kf.get("evt_1") == []                          # kept for 24 hours only


async def test_twilio_routes_off_when_calls_are_simulated(stdb, settings, clock):
    c, *_ = client(stdb, settings, clock)
    assert (await c.post("/twilio/gather?job=call_1", data={"Digits": "1"})).status_code == 404
    assert (await c.get("/audio/abc")).status_code == 404


async def test_twilio_gather_checks_the_signature_then_acknowledges(stdb, settings, clock):
    settings.twilio_token = "tok"
    make_alert(stdb, status="escalated")
    stdb.t["call_job"].append({"id": "call_1", "alertId": "a_1", "caregiverId": "c_bob", "attempt": 1, "status": "ringing"})
    c, w, _ = client(stdb, settings, clock, calls=TwilioCalls(settings))
    w.live_calls["call_1"] = "CA1"
    form = {"CallSid": "CA1", "Digits": "1"}
    assert (await c.post("/twilio/gather?job=call_1", data=form, headers={"x-twilio-signature": "forged"})).status_code == 403
    assert stdb.t["alert"][0]["ownerId"] is None
    sig = twilio_signature("tok", "https://worker.example.test/twilio/gather?job=call_1", form)
    r = await c.post("/twilio/gather?job=call_1", data=form, headers={"x-twilio-signature": sig})
    assert r.status_code == 200 and "<Say>Thank you" in r.text
    assert stdb.t["alert"][0]["ackedVia"] == "phone_call" and stdb.t["call_job"][0]["status"] == "answered"


async def test_health_shows_no_secrets(stdb, settings, clock):
    settings.twilio_token = "super-secret"
    c, *_ = client(stdb, settings, clock)
    text = (await c.get("/health")).text
    assert "super-secret" not in text and "worker-token" not in text and '"calls":"simulated"' in text
