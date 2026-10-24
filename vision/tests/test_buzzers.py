import time
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from nestwatch_vision.buzzers import BuzzerHub


def make(on_ack=None):
    hub = BuzzerHub(on_ack)
    app = FastAPI()

    @app.websocket("/buzzer")
    async def ws(w: WebSocket):
        await hub.handle(w)
    return hub, TestClient(app)


def wait(cond, t=2.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_a_buzzer_says_hello_receives_a_buzz_and_a_stop():
    hub, c = make()
    with c.websocket_connect("/buzzer") as ws:
        ws.send_json({"type": "hello", "buzzer_id": "buzzer-maria", "battery": 0.82})
        assert wait(lambda: hub.connected() == ["buzzer-maria"])
        assert hub.info["buzzer-maria"]["battery"] == 0.82
        assert hub.send("buzzer-maria", {"type": "buzz", "alert_id": "a_1", "severity": "high"})
        assert ws.receive_json() == {"type": "buzz", "alert_id": "a_1", "severity": "high"}
        assert hub.broadcast({"type": "stop", "alert_id": "a_1", "owner": "Maria"}) == 1
        assert ws.receive_json()["type"] == "stop"
    assert wait(lambda: hub.connected() == [])                         # a closed connection is forgotten
    assert hub.send("buzzer-maria", {"type": "buzz"}) is False


def test_a_tap_reports_which_buzzer_sent_it_and_ignores_a_claimed_identity():
    got = []
    hub, c = make(lambda buzzer, alert: got.append((buzzer, alert)))
    with c.websocket_connect("/buzzer") as ws:
        ws.send_json({"type": "hello", "buzzer_id": "buzzer-maria", "battery": 0.5})
        ws.send_json({"type": "ack", "buzzer_id": "buzzer-bob", "alert_id": "a_7"})     # lying about who it is
        assert wait(lambda: got)
    assert got == [("buzzer-maria", "a_7")]                           # the connection's own identity wins


def test_ping_gets_a_pong_and_a_bad_first_message_is_refused():
    hub, c = make()
    with c.websocket_connect("/buzzer") as ws:
        ws.send_json({"type": "hello", "buzzer_id": "b1", "battery": 1.0})
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
    hub2, c2 = make()
    try:
        with c2.websocket_connect("/buzzer") as ws:
            ws.send_json({"type": "ack", "alert_id": "a_1"})                              # no hello first
            ws.receive_json()
        refused = False
    except Exception:
        refused = True
    assert refused and hub2.connected() == []


def test_a_reconnect_replaces_the_old_connection():
    hub, c = make()
    with c.websocket_connect("/buzzer") as a:
        a.send_json({"type": "hello", "buzzer_id": "b1", "battery": 1.0})
        assert wait(lambda: hub.connected() == ["b1"])
        with c.websocket_connect("/buzzer") as b:
            b.send_json({"type": "hello", "buzzer_id": "b1", "battery": 0.9})
            assert wait(lambda: hub.info["b1"]["battery"] == 0.9)
            assert hub.send("b1", {"type": "buzz", "alert_id": "x", "severity": "high"})
            assert b.receive_json()["type"] == "buzz"                  # the new connection gets it
