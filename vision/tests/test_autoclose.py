import numpy as np

from nestwatch_vision.autoclose import AutoCloser
from nestwatch_vision.zones import Zone

STAIRS = Zone("z_1", "Stairs", np.array([[2.8, 1.9], [4.0, 1.9], [4.0, 3.0], [2.8, 3.0]]), "high")
ZONES = {"z_1": STAIRS}


def owned(**kw):
    return {"id": "a_1", "status": "owned", "track_id": "t4", "zone_id": "z_1", "event_type": "zone_entry", **kw}


def run(closer, alerts, pos, t0, t1, step=0.5):
    out = []
    for t in np.arange(t0, t1, step):
        out += closer.update(alerts, {} if pos is None else {"t4": np.array(pos)}, ZONES, float(t))
    return out


def test_closes_after_ten_seconds_clear_of_the_zone():
    calls = []
    c = AutoCloser(lambda a, why: calls.append((a, why)))
    assert run(c, [owned()], (1.0, 1.0), 0, 9.9) == []
    assert run(c, [owned()], (1.0, 1.0), 10.0, 10.5) == ["a_1"]
    assert calls == [("a_1", "Child moved away from Stairs and stayed clear for 10 s")]
    assert run(c, [owned()], (1.0, 1.0), 11, 30) == []                # once only


def test_near_the_edge_or_unseen_restarts_the_clock():
    c = AutoCloser(lambda a, why: None)
    run(c, [owned()], (1.0, 1.0), 0, 8)
    run(c, [owned()], (2.6, 2.5), 8, 9)                               # 0.2 m from the zone: not clear
    assert run(c, [owned()], (1.0, 1.0), 9, 18.5) == []
    run(c, [owned()], None, 18.5, 19)                                 # out of view: not clear either
    assert run(c, [owned()], (1.0, 1.0), 19, 28.5) == [] and run(c, [owned()], (1.0, 1.0), 28.5, 29.5) == ["a_1"]


def test_only_owned_zone_alerts():
    c = AutoCloser(lambda a, why: None)
    for alert in (owned(status="notified"), owned(status="escalated"), owned(event_type="fall"), owned(zone_id="z_gone")):
        assert run(c, [alert], (1.0, 1.0), 0, 30) == []
