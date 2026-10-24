import asyncio
import json

import httpx
import pytest

from nestwatch_worker.calls import AgentCalls, FallbackCalls, NotRetryable, SimulatedCalls, call_phrase
from tests.conftest import make_alert
from tests.test_app import client

SECRET = "s3cret-for-the-webhook"


def agent(settings, handler=None, seen=None, give_up_s=100.0):
    settings.cartesia_key, settings.cartesia_version = "sk_car_test", "2026-08-14"
    settings.cartesia_agent_id, settings.cartesia_from_number_id, settings.voice_webhook_secret = "agent_1", "ap_1", SECRET

    def default(req: httpx.Request):
        if seen is not None:
            seen.append(json.loads(req.content))
        return httpx.Response(200, json={"calls": [{"agent_call_id": "ac_1"}]})
    return AgentCalls(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler or default)), give_up_s=give_up_s)


INFO = {"room": "Playroom", "alert": "A child entered the Stairs area 20 seconds ago", "caregiver": "Bob", "alert_id": "a_1", "caregiver_id": "c_bob"}


async def test_the_agent_call_carries_the_details_and_a_one_time_token(settings):
    seen = []
    calls = agent(settings, seen=seen)
    cid = await calls.place("call_1", "+15550000002", "unused", on_result=None, info=INFO)
    calls._timers["call_1"].cancel()
    assert cid == "ac_1"
    body = seen[0]
    assert body["agent_id"] == "agent_1" and body["from_number_id"] == "ap_1" and body["ringing_timeout_seconds"] == 30
    (out,) = body["outbound_calls"]
    assert out["to_number"] == "+15550000002"
    v = out["dynamic_variables"]
    assert (v["room"], v["caregiver"], v["alert"]) == ("Playroom", "Bob", INFO["alert"]) and len(v["ack_token"]) >= 24
    assert v["ack_token"] not in calls.tokens                                     # only its hash is kept
    assert calls.take_token(v["ack_token"])["alert"] == "a_1"
    assert calls.take_token(v["ack_token"]) is None                               # works once
    assert calls.take_token("guess") is None and calls.take_token("") is None


async def test_agent_refusals_say_why_and_a_timeout_is_not_retried(settings):
    refuse = agent(settings, lambda req: httpx.Response(401, json={"error": "bad key"}))
    with pytest.raises(RuntimeError, match="cartesia refused the agent call: 401.*bad key"):
        await refuse.place("c", "+15550000002", "", None, INFO)
    nothing = agent(settings, lambda req: httpx.Response(200, json={"calls": [{"error": "number not allowed"}]}))
    with pytest.raises(RuntimeError, match="no call.*number not allowed"):
        await nothing.place("c", "+15550000002", "", None, INFO)

    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)
    with pytest.raises(NotRetryable):
        await agent(settings, slow).place("c", "+15550000002", "", None, INFO)
    with pytest.raises(ValueError):
        await agent(settings).place("c", "555", "", None, INFO)


async def test_nobody_speaking_to_the_agent_counts_as_unanswered(settings):
    got = []

    async def on_result(job, outcome):
        got.append((job, outcome))
    calls = agent(settings, give_up_s=0.05)
    await calls.place("call_1", "+15550000002", "", on_result, INFO)
    await asyncio.sleep(0.15)
    assert got == [("call_1", "no_answer")]


async def test_the_keypad_call_takes_over_when_the_agent_cannot_be_placed(settings):
    placed = []

    class Keypad(SimulatedCalls):
        name = "keypad"

        async def place(self, job_id, phone, text, on_result, info=None):
            placed.append(job_id)
            return "CA1"
    broken = agent(settings, lambda req: httpx.Response(500, json={"error": "down"}))
    both = FallbackCalls(broken, Keypad())
    assert await both.place("call_1", "+15550000002", "hi", None, INFO) == "CA1" and placed == ["call_1"]
    assert both.name == "cartesia_agent+keypad"

    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)
    with pytest.raises(NotRetryable):                                             # it may be ringing already: no second call
        await FallbackCalls(agent(settings, slow), Keypad()).place("call_2", "+15550000002", "hi", None, INFO)
    assert placed == ["call_1"]


def test_the_spoken_phrase_has_no_names_and_covers_the_new_events():
    alert = {"eventType": "possible_distress", "createdAt": 1000.0}
    assert call_phrase(alert, None, 1012.0) == "A child may be in distress: both hands were held at the throat 12 seconds ago"
    assert call_phrase({"eventType": "zone_entry", "createdAt": 1000.0}, "Stairs", 1020.0) == "A child entered the Stairs area 20 seconds ago"


# ---- the webhook the agent's tool calls ----
async def place_and_get_token(stdb, settings, clock):
    seen = []
    calls = agent(settings, seen=seen)
    make_alert(stdb, status="escalated")
    stdb.t["call_job"].append({"id": "call_1", "alertId": "a_1", "caregiverId": "c_bob", "attempt": 1, "status": "ringing"})
    c, w, _ = client(stdb, settings, clock, calls=calls)
    await calls.place("call_1", "+15550000002", "hi", w.on_call_result, INFO)
    w.live_calls["call_1"] = "ac_1"
    return c, w, calls, seen[0]["outbound_calls"][0]["dynamic_variables"]["ack_token"]


AUTH = {"authorization": f"Bearer {SECRET}"}


async def test_saying_im_on_it_acknowledges_by_voice(stdb, settings, clock):
    c, w, calls, token = await place_and_get_token(stdb, settings, clock)
    r = await c.post("/webhooks/voice/ack", json={"token": token, "decision": "acknowledge"}, headers=AUTH)
    assert r.status_code == 200 and "Acknowledged. You are now responsible" in r.text
    assert stdb.t["alert"][0]["ownerId"] == "c_bob" and stdb.t["alert"][0]["ackedVia"] == "voice"
    assert stdb.t["call_job"][0]["status"] in ("answered", "cancelled") and "call_1" not in w.live_calls
    again = await c.post("/webhooks/voice/ack", json={"token": token, "decision": "acknowledge"}, headers=AUTH)
    assert "no longer valid" in again.text                                        # the token worked once


async def test_saying_i_cannot_declines_and_the_next_step_comes_at_once(stdb, settings, clock):
    c, w, calls, token = await place_and_get_token(stdb, settings, clock)
    r = await c.post("/webhooks/voice/ack", json={"token": token, "decision": "decline"}, headers=AUTH)
    assert "next person is being told now" in r.text
    assert stdb.t["alert"][0]["status"] == "unanswered" and stdb.t["alert"][0]["ownerId"] is None
    assert any(e["kind"] == "declined" and "via voice" in e["text"] for e in stdb.t["incident_event"])


async def test_an_alert_someone_else_already_took_is_said_so(stdb, settings, clock):
    c, w, calls, token = await place_and_get_token(stdb, settings, clock)
    await stdb.call("acknowledge_alert", ["a_1", "c_maria", "buzzer"])
    r = await c.post("/webhooks/voice/ack", json={"token": token, "decision": "acknowledge"}, headers=AUTH)
    assert "already handled by Maria" in r.text


async def test_the_webhook_is_refused_without_the_secret_or_with_a_bad_decision(stdb, settings, clock):
    c, w, calls, token = await place_and_get_token(stdb, settings, clock)
    body = {"token": token, "decision": "acknowledge"}
    assert (await c.post("/webhooks/voice/ack", json=body)).status_code == 401
    assert (await c.post("/webhooks/voice/ack", json=body, headers={"authorization": "Bearer wrong"})).status_code == 401
    assert (await c.post("/webhooks/voice/ack", json={**body, "decision": "maybe"}, headers=AUTH)).status_code == 422
    assert stdb.t["alert"][0]["ownerId"] is None                                  # nothing happened
