import asyncio
import json
from datetime import datetime

from nestwatch_worker import ai
from nestwatch_worker.calls import SimulatedCalls
from nestwatch_worker.jobs import Worker
from nestwatch_worker.store import KeyframeStore
from tests.conftest import fake_response, make_alert
from tests.test_ai import FakeClient


def worker(stdb, settings, clock, calls=None, claude=None):
    kf = KeyframeStore(clock=clock)
    return Worker(stdb, settings, claude, calls or SimulatedCalls("no_answer", ring_s=0.0), kf, clock=clock)


def queue_call(stdb, alert_id="a_1", job="call_1"):
    stdb.t["call_job"].append({"id": job, "alertId": alert_id, "caregiverId": "c_bob", "attempt": 1, "status": "queued"})


def reducers(stdb, name):
    return [args for r, args in stdb.calls if r == name]


async def test_backup_presses_1_acknowledges_by_phone(stdb, settings, clock):
    make_alert(stdb, status="escalated")
    queue_call(stdb)
    calls = SimulatedCalls("press1", ring_s=0.0)
    w = worker(stdb, settings, clock, calls)
    clock.t = 1025
    await w.poll()
    await w.idle()
    await asyncio.sleep(0.01)
    await w.idle()
    assert calls.placed[0][1] == "0002" and "20" not in calls.placed[0][2] and "25 seconds ago" in calls.placed[0][2]
    updates = reducers(stdb, "update_call_job")
    assert updates == [["call_1", "ringing"], ["call_1", "answered"]]              # answered BEFORE the ack cancels the job
    assert reducers(stdb, "acknowledge_alert") == [["a_1", "c_bob", "phone_call"]]
    assert stdb.t["call_job"][0]["status"] == "answered" and stdb.t["alert"][0]["status"] == "owned"


async def test_no_answer_marks_the_call_failed(stdb, settings, clock):
    make_alert(stdb, status="escalated")
    queue_call(stdb)
    w = worker(stdb, settings, clock)
    await w.poll()
    for _ in range(3):
        await asyncio.sleep(0.01)
        await w.idle()
    assert stdb.t["call_job"][0]["status"] == "failed" and not reducers(stdb, "acknowledge_alert")


async def test_provider_error_is_retried_then_failed(stdb, settings, clock):
    make_alert(stdb, status="escalated")
    queue_call(stdb)
    w = worker(stdb, settings, clock, SimulatedCalls("error"))
    await w.poll()
    await w.idle()
    assert stdb.t["call_job"][0]["status"] == "failed" and w.stats["calls_failed"] == 1
    await w.poll()                                   # the same job is never dialled twice
    await w.idle()
    assert len(reducers(stdb, "update_call_job")) == 1


async def test_acknowledged_meanwhile_hangs_up(stdb, settings, clock):
    make_alert(stdb, status="escalated")
    queue_call(stdb)
    calls = SimulatedCalls("press1", ring_s=30.0)
    hung = []

    async def hang_up(job_id, call_id):
        hung.append((job_id, call_id))
    calls.hang_up = hang_up
    w = worker(stdb, settings, clock, calls)
    await w.poll()
    await w.idle()
    await stdb.call("acknowledge_alert", ["a_1", "c_maria", "buzzer"])        # Maria tapped her buzzer
    await w.poll()
    await w.idle()
    assert hung == [("call_1", "sim_call_1")] and not w.live_calls
    await w.on_call_result("call_1", "pressed_1")                               # a late key press changes nothing
    assert stdb.t["alert"][0]["ownerId"] == "c_maria"


async def test_closed_alert_gets_a_plain_report_without_claude(stdb, settings, clock):
    a = make_alert(stdb, status="closed")
    stdb.log("a_1", "acknowledged", "Maria is handling it (via buzzer)", at=1003)
    w = worker(stdb, settings, clock)
    await w.poll()
    await w.idle()
    r = stdb.t["report"][0]
    assert r["alertId"] == "a_1" and "without an AI summary" in r["summary"] and len(r["lines"]) == 2
    assert a["status"] == "reported"


async def test_claude_report_lines_are_checked(stdb, settings, clock):
    make_alert(stdb, status="closed")
    ev = stdb.t["incident_event"][0]["id"]
    answer = {"summary": "Child 4 entered the stairs area.", "lines": [{"event_id": ev, "text": "Child 4 entered."},
                                                                       {"event_id": "e_404", "text": "Invented."}]}
    claude = ai.Claude(FakeClient(fake_response(json.dumps(answer))), "claude-haiku-4-5", "claude-opus-5-5")
    w = worker(stdb, settings, clock, claude=claude)
    await w.poll()
    await w.idle()
    r = stdb.t["report"][0]
    assert r["summary"] == "Child 4 entered the stairs area." and r["lines"] == [[ev, "Child 4 entered."]]
    assert w.stats["lines_dropped"] == 1


async def test_report_falls_back_when_claude_errors(stdb, settings, clock):
    make_alert(stdb, status="closed")

    class Broken:
        async def report(self, *a):
            raise RuntimeError("overloaded")
    w = worker(stdb, settings, clock, claude=Broken())
    await w.poll()
    await w.idle()
    assert "without an AI summary" in stdb.t["report"][0]["summary"]


async def test_second_opinion_lowers_a_medium_alert(stdb, settings, clock):
    make_alert(stdb, severity="medium", event="unsupervised", zone="", clip="evt_9")
    answer = {"verdict": "lower", "lower_to": "low", "reason": "An adult is sitting beside the child at the left edge."}
    claude = ai.Claude(FakeClient(fake_response(json.dumps(answer))), "claude-haiku-4-5", "claude-opus-5-5")
    w = worker(stdb, settings, clock, claude=claude)
    w.keyframes.put("evt_9", [b"\xff\xd8frame"])
    await w.poll()
    await w.idle()
    assert reducers(stdb, "set_urgency") == [["a_1", "Second opinion (Claude): An adult is sitting beside the child at the left edge.", "low"]]
    await w.poll()
    await w.idle()
    assert len(reducers(stdb, "set_urgency")) == 1                              # once per alert


async def test_second_opinion_waits_for_frames_and_skips_high(stdb, settings, clock):
    make_alert(stdb, id="a_1", severity="high", clip="evt_1")
    make_alert(stdb, id="a_2", severity="medium", event="unsupervised", clip="evt_2")
    client = FakeClient(fake_response(json.dumps({"verdict": "confirm", "lower_to": None, "reason": "r"})))
    w = worker(stdb, settings, clock, claude=ai.Claude(client, "claude-haiku-4-5", "claude-opus-5-5"))
    w.keyframes.put("evt_1", [b"\xff\xd8"])
    await w.poll()
    await w.idle()
    assert client.messages.seen == []                    # high: never; medium: still waiting for its frames
    clock.t += 9                                         # waited long enough; still no frames: skip, do not guess blind
    await w.poll()
    await w.idle()
    assert client.messages.seen == [] and "a_2" in w._opinion_done


async def test_late_second_opinion_is_ignored(stdb, settings, clock):
    make_alert(stdb, severity="medium", event="unsupervised", clip="evt_9")
    settings.second_opinion_timeout_s = 0.05
    answer = {"verdict": "lower", "lower_to": "low", "reason": "adult nearby"}
    claude = ai.Claude(FakeClient(fake_response(json.dumps(answer)), delay=1.0), "claude-haiku-4-5", "claude-opus-5-5")
    w = worker(stdb, settings, clock, claude=claude)
    w.keyframes.put("evt_9", [b"\xff\xd8"])
    await w.poll()
    await w.idle()
    assert not reducers(stdb, "set_urgency") and w.stats["opinions_late"] == 1


async def test_daily_summary_once_after_closing_time(stdb, settings, clock):
    day_start = datetime(2026, 10, 24).timestamp()
    make_alert(stdb, status="reported", created=day_start + 10 * 3600)
    make_alert(stdb, id="a_old", status="reported", created=day_start - 3600)    # yesterday: not counted
    clock.t = day_start + 17 * 3600
    w = worker(stdb, settings, clock)
    await w.poll()
    await w.idle()
    assert not stdb.t["report"]
    clock.t = day_start + 18 * 3600 + 60
    await w.poll()
    await w.idle()
    (r,) = stdb.t["report"]
    assert r["kind"] == "daily" and r["summary"].startswith("Daily summary 2026-10-24: 1 alerts today (1 high")
    w2 = worker(stdb, settings, clock)                    # a restarted worker does not write it again
    await w2.poll()
    await w2.idle()
    assert len(stdb.t["report"]) == 1


async def test_backstop_calls_escalate_due_and_survives_outages(stdb, settings, clock):
    w = worker(stdb, settings, clock)
    await w.poll()
    assert reducers(stdb, "escalate_due") == [[]]
    stdb.down = True
    task = asyncio.create_task(w.run())
    await asyncio.sleep(0.05)
    assert not w.online and w.poll_errors >= 1
    stdb.down = False
    await asyncio.sleep(0.05)
    assert w.online
    task.cancel()


async def test_after_an_outage_only_the_newest_queued_call_is_dialled(stdb, settings, clock):
    make_alert(stdb, status="unanswered")
    queue_call(stdb, job="call_1")
    stdb.t["call_job"].append({"id": "call_2", "alertId": "a_1", "caregiverId": "c_bob", "attempt": 2, "status": "queued"})
    calls = SimulatedCalls("no_answer", ring_s=30.0)
    w = worker(stdb, settings, clock, calls)
    await w.poll()
    await w.idle()
    assert [p[0] for p in calls.placed] == ["call_2"]
    assert {j["id"]: j["status"] for j in stdb.t["call_job"]} == {"call_1": "failed", "call_2": "ringing"}
    for t in list(calls._tasks.values()):
        t.cancel()


class RecordingCalls:
    name = "recording"

    def __init__(self):
        self.placed, self.hung_up = [], []

    async def place(self, job_id, phone, text, on_result, info=None):
        self.placed.append(job_id)
        return f"CA_{job_id}"

    async def hang_up(self, job_id, call_id):
        self.hung_up.append((job_id, call_id))


async def test_a_later_attempt_hangs_up_an_earlier_one_that_is_still_ringing(stdb, settings, clock):
    make_alert(stdb, status="escalated")
    queue_call(stdb, job="call_1")
    calls = RecordingCalls()
    w = worker(stdb, settings, clock, calls)
    await w.poll()
    await w.idle()
    assert calls.placed == ["call_1"] and stdb.t["call_job"][0]["status"] == "ringing"
    stdb.t["call_job"].append({"id": "call_2", "alertId": "a_1", "caregiverId": "c_bob", "attempt": 2, "status": "queued"})
    await w.poll()
    await w.idle()
    assert calls.placed == ["call_1", "call_2"]
    assert calls.hung_up == [("call_1", "CA_call_1")]                       # one phone, one call at a time
    assert {j["id"]: j["status"] for j in stdb.t["call_job"]} == {"call_1": "failed", "call_2": "ringing"}


async def test_the_backup_also_gets_a_text_with_the_key_frame(stdb, settings, clock):
    from nestwatch_worker.calls import SimulatedTexts
    make_alert(stdb, status="escalated")
    queue_call(stdb)
    w = worker(stdb, settings, clock)
    w.texts = SimulatedTexts()
    w.keyframes.put(stdb.t["alert"][0]["clipRef"], [b"\xff\xd8frame"])
    await w.poll()
    await w.idle()
    assert [(last4, img) for last4, _, img in w.texts.sent] == [(w.texts.sent[0][0], True)]
    assert "nobody has answered yet" in w.texts.sent[0][1]
