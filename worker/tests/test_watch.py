from nestwatch_worker.watch import WatchKeys, normalize, watch_state
from tests.conftest import make_alert
from tests.test_app import MARIA, client


def test_pairing_codes_are_typable_hashed_and_replaced(tmp_path):
    keys = WatchKeys(str(tmp_path / "k.json"))
    code = keys.pair("c_maria")
    assert len(code) == 11 and code[5] == "-" and set(code.replace("-", "")) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
    assert keys.who(code) == "c_maria" and keys.who(code.lower().replace("-", " ")) == "c_maria"     # typed sloppily on a phone
    assert normalize(code) not in (tmp_path / "k.json").read_text()                                  # only the hash is stored
    new = keys.pair("c_maria")
    assert keys.who(code) is None and keys.who(new) == "c_maria"                                     # the old code stopped working
    assert WatchKeys(str(tmp_path / "k.json")).who(new) == "c_maria"                                 # survives a restart


def test_too_many_wrong_codes_slow_everyone_down(tmp_path):
    t = [1000.0]
    keys = WatchKeys(str(tmp_path / "k.json"), max_failures_per_minute=3, clock=lambda: t[0])
    for _ in range(3):
        assert keys.who("WRONGWRONG") is None
    assert keys.throttled()
    t[0] += 61
    assert not keys.throttled()


def test_state_puts_untaken_alerts_first_and_says_when_to_buzz():
    me = {"id": "c_maria", "name": "Maria"}
    alerts = [
        {"id": "a_1", "trackId": "t4", "eventType": "zone_entry", "zoneId": "z_1", "severity": "medium", "status": "owned",
         "createdAt": 900.0, "ownerId": "c_bob", "nextEscalationAt": None, "escalationLevel": 0},
        {"id": "a_2", "trackId": "t7", "eventType": "fall", "zoneId": "", "severity": "high", "status": "notified",
         "createdAt": 990.0, "ownerId": None, "nextEscalationAt": 1012.0, "escalationLevel": 0},
    ]
    s = watch_state(me, alerts, {"z_1": "Stairs"}, {"t7": "7"}, {"c_bob": "Bob"}, now=1000.0)
    assert s["me"] == "Maria" and s["count"] == 1 and s["buzz"] == "high"
    first, second = s["alerts"]
    assert (first["id"], first["what"], first["child"], first["waiting"], first["next_in"], first["next"]) == ("a_2", "Possible fall", "7", True, 12, "Backup is called")
    assert (second["id"], second["where"], second["owner"], second["waiting"]) == ("a_1", "Stairs", "Bob", False)
    assert watch_state(me, [], {}, {}, {}, 1000.0)["buzz"] is None


async def test_a_caregiver_pairs_a_watch_and_the_watch_acknowledges_with_it(stdb, settings, clock):
    c, w, _ = client(stdb, settings, clock)
    assert (await c.post("/watch/pair")).status_code == 401                                  # signed-in caregivers only
    code = (await c.post("/watch/pair", headers=MARIA)).json()["code"]
    make_alert(stdb, severity="high", status="notified")
    assert (await c.get("/watch/state")).status_code == 401
    assert (await c.get("/watch/state", headers={"x-watch-key": "WRONG-CODE1"})).status_code == 401
    state = (await c.get("/watch/state", headers={"x-watch-key": code})).json()
    assert state["me"] == "Maria" and state["buzz"] == "high" and state["alerts"][0]["id"] == "a_1"
    r = await c.post("/watch/act", json={"alert_id": "a_1", "decision": "acknowledge"}, headers={"x-watch-key": code})
    assert r.status_code == 200 and r.json()["say"] == "You have it"
    assert stdb.t["alert"][0]["ownerId"] == "c_maria" and stdb.t["alert"][0]["ackedVia"] == "watch"
    after = (await c.get("/watch/state", headers={"x-watch-key": code})).json()
    assert after["buzz"] is None and after["alerts"][0]["owner"] == "you"


async def test_the_watch_can_decline_and_bad_requests_are_refused(stdb, settings, clock):
    c, w, _ = client(stdb, settings, clock)
    code = (await c.post("/watch/pair", headers=MARIA)).json()["code"]
    make_alert(stdb, severity="high", status="notified")
    key = {"x-watch-key": code}
    r = await c.post("/watch/act", json={"alert_id": "a_1", "decision": "decline"}, headers=key)
    assert r.json()["say"] == "Next person told" and stdb.t["alert"][0]["status"] == "escalated"
    assert (await c.post("/watch/act", json={"alert_id": "a_1", "decision": "maybe"}, headers=key)).status_code == 422
    assert (await c.post("/watch/act", json={"alert_id": "a_1'; --", "decision": "acknowledge"}, headers=key)).status_code == 422
