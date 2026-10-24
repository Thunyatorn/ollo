from nestwatch_vision.coordinator import AlertCoordinator

CG = [{"id": "c_maria", "name": "Maria", "role": "primary", "buzzer_id": "buzzer-maria", "on_duty": True},
      {"id": "c_bob", "name": "Bob", "role": "backup", "buzzer_id": "buzzer-bob", "on_duty": True},
      {"id": "c_sam", "name": "Sam", "role": "staff", "buzzer_id": "buzzer-sam", "on_duty": True},
      {"id": "c_off", "name": "Off", "role": "primary", "buzzer_id": "buzzer-off", "on_duty": False},
      {"id": "c_nobuzz", "name": "NoBuzzer", "role": "staff", "buzzer_id": None, "on_duty": True}]


class FakeHub:
    def __init__(self, connected=("buzzer-maria", "buzzer-bob", "buzzer-sam", "buzzer-off")):
        self.sent, self.connected = [], set(connected)

    def send(self, b, m):
        if b not in self.connected:
            return False
        self.sent.append((b, m)); return True

    def broadcast(self, m):
        for b in self.connected:
            self.sent.append((b, m))
        return len(self.connected)


class FakeAlarm:
    def __init__(self):
        self.on = {}

    def start(self, reason, duration_s=None):
        self.on[reason] = duration_s

    def stop(self, reason):
        self.on.pop(reason, None)


def alert(status="notified", sev="high", owner=None, aid="a_1"):
    return {"id": aid, "status": status, "severity": sev, "owner_id": owner}


def make():
    hub, alarm, acks = FakeHub(), FakeAlarm(), []
    return AlertCoordinator(hub, alarm, lambda a, c: acks.append((a, c))), hub, alarm, acks


def kinds(hub):
    return [(b, m["type"]) for b, m in hub.sent]


def test_new_high_alert_buzzes_only_the_on_duty_primary():
    c, hub, alarm, _ = make()
    c.tick([alert()], CG)
    assert kinds(hub) == [("buzzer-maria", "buzz")]
    assert hub.sent[0][1] == {"type": "buzz", "alert_id": "a_1", "severity": "high"}
    c.tick([alert()], CG)
    assert len(hub.sent) == 1                                          # polling again does not buzz again
    assert not alarm.on


def test_low_alerts_are_app_only_and_never_buzz():
    c, hub, _, _ = make()
    c.tick([alert(sev="low")], CG)
    assert hub.sent == []


def test_escalation_adds_the_backup_then_unanswered_adds_everyone_and_the_alarm():
    c, hub, alarm, _ = make()
    c.tick([alert("notified")], CG)
    c.tick([alert("escalated")], CG)
    assert kinds(hub) == [("buzzer-maria", "buzz"), ("buzzer-bob", "buzz")]          # Maria is not buzzed twice
    assert not alarm.on
    c.tick([alert("unanswered")], CG)
    assert ("buzzer-sam", "buzz") in kinds(hub) and ("buzzer-off", "buzz") not in kinds(hub)   # on-duty only, with a buzzer
    assert "unanswered:a_1" in alarm.on                                # loud local alarm


def test_taking_the_alert_stops_every_buzzer_and_the_alarm():
    c, hub, alarm, _ = make()
    c.tick([alert("unanswered")], CG)
    assert alarm.on
    hub.sent.clear()
    c.tick([alert("owned", owner="c_bob")], CG)
    stops = [(b, m) for b, m in hub.sent if m["type"] == "stop"]
    assert stops and all(m["owner"] == "Bob" and m["alert_id"] == "a_1" for _, m in stops)
    assert not alarm.on
    n = len(hub.sent)
    c.tick([alert("owned", owner="c_bob")], CG)
    assert len(hub.sent) == n                                          # stop is sent once


def test_closing_an_alert_also_stops_it_and_a_vanished_alert_is_forgotten():
    c, hub, alarm, _ = make()
    c.tick([alert("unanswered")], CG)
    c.tick([alert("closed")], CG)
    assert alarm.on == {}
    c.tick([alert("unanswered", aid="a_2")], CG)
    c.tick([], CG)                                                     # the row left the table
    assert alarm.on == {} and "a_2" not in c.buzzed


def test_a_buzzer_that_is_not_connected_is_retried_on_the_next_tick():
    hub = FakeHub(connected=())
    c = AlertCoordinator(hub, FakeAlarm(), lambda a, b: None)
    c.tick([alert()], CG)
    assert hub.sent == []
    hub.connected.add("buzzer-maria")
    c.tick([alert()], CG)
    assert kinds(hub) == [("buzzer-maria", "buzz")]


def test_a_tap_acknowledges_as_the_caregiver_paired_with_that_buzzer():
    c, _, _, acks = make()
    c.tick([alert()], CG)
    assert c.on_buzzer_ack("buzzer-maria", "a_1") is True
    assert acks == [("a_1", "c_maria")]
    assert c.on_buzzer_ack("buzzer-unknown", "a_1") is False           # an unpaired buzzer cannot acknowledge anything
    assert c.on_buzzer_ack("buzzer-maria", "") is False
    assert acks == [("a_1", "c_maria")]


def test_a_high_event_while_spacetime_is_down_sounds_the_alarm_itself():
    c, _, alarm, _ = make()
    c.on_local_event("evt_1", "high", spacetime_online=True)
    c.on_local_event("evt_2", "medium", spacetime_online=False)
    assert alarm.on == {}
    c.on_local_event("evt_3", "high", spacetime_online=False)
    assert alarm.on == {"offline:evt_3": 30.0}                         # times itself out: nobody can silence it from here


def test_an_alert_taken_and_closed_between_two_polls_still_stops_the_buzzers():
    c, hub, alarm, _ = make()
    c.tick([alert("notified")], CG)
    hub.sent.clear()
    c.tick([], CG)                                                     # next poll: it is already closed, so not in the live set
    assert [m["type"] for _, m in hub.sent] and all(m["type"] == "stop" and m["alert_id"] == "a_1" for _, m in hub.sent)
