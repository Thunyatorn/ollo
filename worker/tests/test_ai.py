import asyncio
import json
from types import SimpleNamespace

import pytest

from nestwatch_worker import ai
from tests.conftest import fake_response

AREAS = ["Kitchen gate", "Book shelf"]


# ---- second opinion: may only lower medium/low ----
def test_opinion_lowers_medium_to_low():
    v = ai.check_opinion({"verdict": "lower", "lower_to": "low", "reason": "An adult is kneeling next to the child."}, "medium")
    assert v == {"lower_to": "low", "note": "Second opinion (Claude): An adult is kneeling next to the child."}


@pytest.mark.parametrize("data,severity", [
    ({"verdict": "lower", "lower_to": "low", "reason": "x"}, "high"),          # high is never touched
    ({"verdict": "lower", "lower_to": "medium", "reason": "x"}, "medium"),     # not lower
    ({"verdict": "lower", "lower_to": "high", "reason": "x"}, "medium"),       # raising is not allowed
    ({"verdict": "confirm", "lower_to": None, "reason": "x"}, "medium"),
    ({"verdict": "unsure", "lower_to": "low", "reason": "x"}, "medium"),
    ({"verdict": "lower", "lower_to": "low", "reason": ""}, "medium"),         # no reason, no change
    ({"verdict": "lower", "lower_to": "low", "reason": "The child was injured."}, "medium"),   # no diagnoses
    ({}, "medium"),
])
def test_opinion_refused(data, severity):
    assert ai.check_opinion(data, severity) is None


# ---- rule drafts ----
def test_rule_uses_the_listed_area_name_exactly():
    d = ai.check_rule({"area_name": "kitchen GATE", "schedule": {"named": "nap_time", "start": None, "end": None},
                       "severity": "high", "escalation": "buzzer_then_call", "needs_drawing": False, "question": None}, AREAS)
    assert d == {"needs_drawing": False, "area_name": "Kitchen gate", "schedule": {"named": "nap_time", "startMin": None, "endMin": None},
                 "severity": "high", "escalation": "buzzer_then_call"}


def test_rule_unknown_area_needs_drawing():
    d = ai.check_rule({"area_name": "Pool", "schedule": {}, "severity": "high", "escalation": "buzzer_then_call", "needs_drawing": False}, AREAS)
    assert d["needs_drawing"] and "floor plan" in d["question"]


def test_rule_clock_window_and_bad_times():
    base = {"area_name": "Book shelf", "severity": "medium", "escalation": "buzzer_only", "needs_drawing": False}
    d = ai.check_rule({**base, "schedule": {"named": None, "start": "12:30", "end": "14:30"}}, AREAS)
    assert d["schedule"] == {"named": None, "startMin": 750, "endMin": 870}
    for start, end in [("12:30", None), ("25:00", "26:00"), ("12:30", "12:30"), ("noon", "14:00")]:
        bad = ai.check_rule({**base, "schedule": {"named": None, "start": start, "end": end}}, AREAS)
        assert bad.get("unclear_time") and "When" in bad["question"]
    assert ai.check_rule({**base, "schedule": {"named": "lunch", "start": None, "end": None}}, AREAS)["unclear_time"]


def test_rule_bad_severity_and_escalation_fall_back_to_safe_defaults():
    d = ai.check_rule({"area_name": "Book shelf", "schedule": {"named": None, "start": None, "end": None},
                       "severity": "critical", "escalation": "sms", "needs_drawing": False}, AREAS)
    assert (d["severity"], d["escalation"]) == ("high", "buzzer_then_call")


def test_keyword_rule_matches_the_spec_example():
    d = ai.keyword_rule("Keep kids away from the kitchen gate during nap time.", AREAS)
    assert d["area_name"] == "Kitchen gate" and d["schedule"]["named"] == "nap_time" and d["severity"] == "high"


def test_keyword_rule_window_and_ambiguity():
    d = ai.keyword_rule("Nobody near the book shelf from 9:00 to 10:30", AREAS)
    assert d["schedule"] == {"named": None, "startMin": 540, "endMin": 630} and d["severity"] == "medium"
    assert ai.keyword_rule("Keep them away from the pool", AREAS)["needs_drawing"]
    assert ai.keyword_rule("Not the book shelf or the kitchen gate", AREAS)["needs_drawing"]


# ---- reports ----
EVENTS = [{"id": "e_1", "at": 1000.0, "kind": "detected", "text": "zone_entry (high) in zone z_stairs"},
          {"id": "e_2", "at": 1004.0, "kind": "acknowledged", "text": "Maria is handling it (via buzzer)"},
          {"id": "e_3", "at": 1030.0, "kind": "closed", "text": "child back in play area"}]


def test_report_drops_uncited_and_diagnosing_lines():
    data = {"summary": "Child 4 entered the stairs area; Maria handled it.",
            "lines": [{"event_id": "e_1", "text": "Child 4 entered the stairs area."},
                      {"event_id": "e_99", "text": "Made-up line."},
                      {"event_id": "e_2", "text": "Child 4 got hurt on the stairs."},
                      {"event_id": "e_3", "text": "The alert was closed."}]}
    summary, lines, dropped = ai.check_report(data, EVENTS)
    assert summary.startswith("Child 4") and dropped == 2
    assert [l["eventId"] for l in lines] == ["e_1", "e_3"]


def test_plain_report_has_every_event_and_says_it_is_plain():
    alert = {"trackId": "t4", "eventType": "zone_entry", "zoneId": "z_stairs", "severity": "high", "createdAt": 1000.0}
    summary, lines = ai.plain_report(alert, list(reversed(EVENTS)), "Stairs")
    assert "Child 4 entered Stairs" in summary and "Maria is handling it" in summary and "without an AI summary" in summary
    assert [l["eventId"] for l in lines] == ["e_1", "e_2", "e_3"]


# ---- the Claude client ----
class FakeMessages:
    def __init__(self, response=None, delay=0.0):
        self.response, self.delay, self.seen = response, delay, []

    async def create(self, **kw):
        self.seen.append(kw)
        await asyncio.sleep(self.delay)
        return self.response


class FakeClient:
    def __init__(self, response=None, delay=0.0):
        self.messages = FakeMessages(response, delay)
        self.beta = SimpleNamespace(messages=self.messages)
        self.options = []

    def with_options(self, **kw):
        self.options.append(kw)
        return self


async def test_strong_model_uses_fallbacks_effort_and_schema():
    client = FakeClient(fake_response(json.dumps({"summary": "s", "lines": []})))
    c = ai.Claude(client, "claude-haiku-4-5", "claude-opus-5-5")
    alert = {"trackId": "t4", "eventType": "zone_entry", "zoneId": "z", "severity": "high", "createdAt": 1000.0}
    assert await c.report(alert, "Stairs", EVENTS) == {"summary": "s", "lines": []}
    kw = client.messages.seen[0]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    assert kw["output_config"]["effort"] == "low" and kw["output_config"]["format"]["type"] == "json_schema"
    assert "e_2" in kw["messages"][0]["content"][0]["text"]


async def test_fast_model_gets_no_effort_or_fallbacks_and_images_are_sent():
    client = FakeClient(fake_response(json.dumps({"verdict": "unsure", "lower_to": None, "reason": "dark"})))
    c = ai.Claude(client, "claude-haiku-4-5", "claude-opus-5-5")
    alert = {"trackId": "t2", "eventType": "unsupervised", "zoneId": "", "severity": "medium", "createdAt": 1000.0}
    out = await c.second_opinion(alert, None, EVENTS, [b"\xff\xd8one", b"\xff\xd8two"], timeout=5.0)
    assert out["verdict"] == "unsure"
    kw = client.messages.seen[0]
    assert "fallbacks" not in kw and "effort" not in kw["output_config"]
    assert sum(b["type"] == "image" for b in kw["messages"][0]["content"]) == 2
    assert client.options[0] == {"timeout": 5.0, "max_retries": 0}


async def test_refusal_and_cut_off_answers_are_none():
    for stop in ("refusal", "max_tokens"):
        c = ai.Claude(FakeClient(fake_response("{}", stop)), "claude-haiku-4-5", "claude-opus-5-5")
        assert await c.draft_rule("x", AREAS) is None
    c = ai.Claude(FakeClient(fake_response("not json")), "claude-haiku-4-5", "claude-opus-5-5")
    assert await c.draft_rule("x", AREAS) is None


async def test_second_opinion_hard_time_limit():
    c = ai.Claude(FakeClient(fake_response("{}"), delay=2.0), "claude-haiku-4-5", "claude-opus-5-5")
    alert = {"trackId": "t2", "eventType": "unsupervised", "zoneId": "", "severity": "medium", "createdAt": 1000.0}
    with pytest.raises(asyncio.TimeoutError):
        await c.second_opinion(alert, None, EVENTS, [b"\xff\xd8"], timeout=0.05)
