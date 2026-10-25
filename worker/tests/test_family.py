"""Family emergency actions (CLUADE.md "Family emergency actions"): mocked HTTP, a fake mail sender, simulated calls.
Nothing here sends email, Telegram messages or calls."""
import asyncio
import json

import httpx
import pytest

from tests.conftest import make_alert
from nestwatch_worker.calls import SimulatedCalls
from nestwatch_worker.family import Family
from nestwatch_worker.store import KeyframeStore

FAMILY = "111"
JPEG = b"\xff\xd8\xff-frame"
CLIP = b"\x00\x00\x00\x18ftypmp42-clip"


class FakeServices:
    """Telegram, OpenStreetMap and the vision service's clip endpoint, recording every request."""

    def __init__(self, hospitals=None, clip_after=0):
        self.sent, self.answers, self.osm = [], [], 0
        self.hospitals = hospitals if hospitals is not None else []
        self.clip_after = clip_after                       # 404s before the clip is ready

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "api.telegram.org" in url:
            method = url.rsplit("/", 1)[1]
            if method == "answerCallbackQuery":
                self.answers.append(dict(httpx.QueryParams(request.content.decode())))
            else:
                self.sent.append((method, request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.sent)}})
        if "overpass" in url:
            self.osm += 1
            return httpx.Response(200, json={"elements": self.hospitals})
        if "/clips/" in url:
            if self.clip_after > 0:
                self.clip_after -= 1
                return httpx.Response(404)
            return httpx.Response(200, content=CLIP, headers={"content-type": "video/mp4"})
        return httpx.Response(404)

    def texts(self):
        return [body.decode(errors="ignore") for _, body in self.sent]


@pytest.fixture
def family_settings(settings, tmp_path):
    record = tmp_path / "record.json"
    record.write_text(json.dumps({"name": "Ruth Example", "conditions": ["atrial fibrillation"], "medications": ["warfarin"]}))
    settings.telegram_token, settings.telegram_chat_id = "bot-token", FAMILY
    settings.patient_name, settings.home_address = "Ruth", "12 Oak St, Berkeley"
    settings.home_lat, settings.home_lon = "37.8700", "-122.2700"
    settings.medical_record_file = str(record)
    settings.hospital_name, settings.hospital_address, settings.hospital_email = "Alta Bates", "2450 Ashby Ave", "er@altabates.test"
    settings.hospital_fallback_email = "standin@example.test"
    settings.smtp_from, settings.ambulance_number = "ollo@example.test", "+15550001234"
    settings.vision_http = "http://vision.test"
    return settings


def make_family(settings, stdb, services, calls=None, keyframes=None):
    mails = []

    async def send_email(message):
        mails.append(message)

    async def no_wait(_):
        await asyncio.sleep(0)

    family = Family(settings, stdb, calls or SimulatedCalls("no_answer", ring_s=0.01), keyframes or KeyframeStore(),
                    http=httpx.AsyncClient(transport=httpx.MockTransport(services)), send_email=send_email, sleep=no_wait)
    return family, mails


def press(data, chat=FAMILY, n=1):
    return {"update_id": n, "callback_query": {"id": f"cb{n}", "data": data, "message": {"chat": {"id": int(chat)}}}}


def test_fall_message_goes_out_once_with_photo_caption_and_two_buttons(family_settings, stdb):
    services = FakeServices()
    keyframes = KeyframeStore()
    alert = make_alert(stdb, id="a_1", event="fall", clip="evt_1")
    keyframes.put("evt_1", [JPEG])
    family, _ = make_family(family_settings, stdb, services, keyframes=keyframes)
    asyncio.run(family.on_alert(alert))
    asyncio.run(family.on_alert(alert))                      # the same alert reported again: no second message
    assert len(services.sent) == 1
    method, body = services.sent[0]
    text = body.decode(errors="ignore")
    assert method == "sendPhoto" and JPEG.decode(errors="ignore") in text
    assert "possible fall" in text and "Ruth" in text and "12 Oak St, Berkeley" in text and "Alta Bates (usual)" in text
    assert "Send report to hospital" in text and "Call ambulance" in text and '"r:a_1"' in text and '"a:a_1"' in text


def test_hospital_is_usual_else_nearest_emergency_hospital(family_settings, stdb):
    near = {"type": "node", "lat": 37.86, "lon": -122.26, "tags": {"name": "Near ER", "amenity": "hospital", "emergency": "yes",
                                                                    "email": "er@near.test", "addr:street": "Main St"}}
    far = {"type": "way", "center": {"lat": 37.99, "lon": -122.50}, "tags": {"name": "Far ER", "amenity": "hospital", "emergency": "yes"}}
    services = FakeServices(hospitals=[far, near])
    family, _ = make_family(family_settings, stdb, services)
    usual = asyncio.run(family.hospital())
    assert usual["name"] == "Alta Bates" and usual["source"] == "usual" and services.osm == 0

    family_settings.hospital_name = family_settings.hospital_email = ""
    family, _ = make_family(family_settings, stdb, services)
    async def twice():
        return await family.hospital(), await family.hospital()
    first, again = asyncio.run(twice())
    assert first["name"] == "Near ER" and first["source"] == "nearest" and first["email"] == "er@near.test"
    assert 0 < first["distance_km"] < 3 and again == first and services.osm == 1     # cached


def test_report_emails_record_clip_and_timeline_once(family_settings, stdb):
    services = FakeServices(clip_after=2)                    # still recording for two checks
    alert = make_alert(stdb, id="a_1", event="fall", clip="evt_1")
    family, mails = make_family(family_settings, stdb, services)
    asyncio.run(family.on_alert(alert))
    asyncio.run(family.handle_update(press("r:a_1", n=2)))
    asyncio.run(family.handle_update(press("r:a_1", n=3)))  # second press: already done
    assert len(mails) == 1
    mail = mails[0]
    assert mail["To"] == "er@altabates.test" and mail["Subject"].startswith("ollo fall report: Ruth")
    body = mail.get_body(("plain",)).get_content()
    assert "12 Oak St, Berkeley" in body and "fall (high)" in body                  # the incident timeline
    files = {part.get_filename(): part.get_content() for part in mail.iter_attachments()}
    assert files["record.json"] and b"warfarin" in files["record.json"] and files["fall-evt_1.mp4"] == CLIP
    assert any("already done" in a.get("text", "").lower() for a in services.answers)
    assert any("er@altabates.test" in t for t in services.texts())
    assert [e["kind"] for e in stdb.t["incident_event"] if e["alertId"] == "a_1"].count("report_sent") == 1


def test_ambulance_needs_a_second_tap_and_calls_once(family_settings, stdb):
    services = FakeServices()
    calls = SimulatedCalls("no_answer", ring_s=0.01)
    alert = make_alert(stdb, id="a_1", event="fall", clip="evt_1")
    family_settings.ambulance_live = True
    family, _ = make_family(family_settings, stdb, services, calls=calls)
    asyncio.run(family.on_alert(alert))
    asyncio.run(family.handle_update(press("a:a_1", n=2)))
    assert calls.placed == []                                # the first tap only asks
    assert any("This is a real phone call" in t and '"y:a_1"' in t and '"n:a_1"' in t for t in services.texts())
    asyncio.run(family.handle_update(press("n:a_1", n=3)))
    assert calls.placed == []                                # cancelled
    asyncio.run(family.handle_update(press("a:a_1", n=4)))
    asyncio.run(family.handle_update(press("y:a_1", n=5)))
    asyncio.run(family.handle_update(press("y:a_1", n=6)))
    assert len(calls.placed) == 1
    _, last4, spoken = calls.placed[0]
    assert last4 == "1234" and "Ruth may have fallen at 12 Oak St, Berkeley" in spoken and "Alta Bates" in spoken
    assert [e["kind"] for e in stdb.t["incident_event"]].count("ambulance_called") == 1


def test_emergency_numbers_are_refused(family_settings, stdb):
    family_settings.ambulance_number = "911"
    services = FakeServices()
    calls = SimulatedCalls("no_answer", ring_s=0.01)
    alert = make_alert(stdb, id="a_1", event="fall", clip="evt_1")
    family, _ = make_family(family_settings, stdb, services, calls=calls)
    asyncio.run(family.on_alert(alert))
    asyncio.run(family.handle_update(press("a:a_1", n=2)))
    asyncio.run(family.handle_update(press("y:a_1", n=3)))
    assert calls.placed == []
    assert "family_action_failed" in [e["kind"] for e in stdb.t["incident_event"]]


def test_buttons_from_other_chats_do_nothing(family_settings, stdb):
    services = FakeServices()
    calls = SimulatedCalls("no_answer", ring_s=0.01)
    alert = make_alert(stdb, id="a_1", event="fall", clip="evt_1")
    family, mails = make_family(family_settings, stdb, services, calls=calls)
    asyncio.run(family.on_alert(alert))
    for n, data in enumerate(["r:a_1", "a:a_1", "y:a_1"], start=2):
        asyncio.run(family.handle_update(press(data, chat="999", n=n)))
    assert mails == [] and calls.placed == []
    assert all("not allowed" in a.get("text", "") for a in services.answers) and len(services.answers) == 3


def test_worker_hands_new_fall_alerts_to_the_family_once(family_settings, stdb, clock):
    from nestwatch_worker.jobs import Worker
    seen = []

    class Recorder:
        async def on_alert(self, alert):
            seen.append(alert["id"])

    make_alert(stdb, id="a_1", event="fall", created=clock.t)
    make_alert(stdb, id="a_2", event="zone_entry", created=clock.t)
    worker = Worker(stdb, family_settings, None, SimulatedCalls("no_answer", 0.01), KeyframeStore(), clock=clock, family=Recorder())
    async def twice():
        await worker.poll(); await worker.poll(); await worker.idle()
    asyncio.run(twice())
    assert seen == ["a_1"]


def test_demo_report_goes_only_to_report_to(family_settings, stdb):
    family_settings.report_to = "demo@example.test"         # a hospital email is set, and must not be used
    services = FakeServices()
    alert = make_alert(stdb, id="a_1", event="fall", clip="evt_1")
    family, mails = make_family(family_settings, stdb, services)
    asyncio.run(family.on_alert(alert))
    asyncio.run(family.handle_update(press("r:a_1", n=2)))
    assert [m["To"] for m in mails] == ["demo@example.test"]
    assert "Alta Bates" in mails[0].get_body(("plain",)).get_content()          # the hospital is only named
    assert not any("er@altabates.test" in t for t in services.texts())


def test_ambulance_demo_places_no_call(family_settings, stdb):
    assert family_settings.ambulance_live is False                              # the default
    services = FakeServices()
    calls = SimulatedCalls("no_answer", ring_s=0.01)
    alert = make_alert(stdb, id="a_1", event="fall", clip="evt_1")
    family, _ = make_family(family_settings, stdb, services, calls=calls)
    asyncio.run(family.on_alert(alert))
    asyncio.run(family.handle_update(press("a:a_1", n=2)))
    assert any("demo" in t.lower() and '"y:a_1"' in t for t in services.texts())
    asyncio.run(family.handle_update(press("y:a_1", n=3)))
    assert calls.placed == []
    said = [t for t in services.texts() if "Demo: no call placed" in t]
    assert said and "Ruth may have fallen at 12 Oak St, Berkeley" in said[0]
    logged = [e for e in stdb.t["incident_event"] if e["kind"] == "ambulance_called"]
    assert len(logged) == 1 and "demo" in logged[0]["text"].lower()
