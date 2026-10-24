"""The pipeline with made-up people: pixels in, floor positions and alert events out."""
import time
from datetime import datetime
import numpy as np
from nestwatch_vision.calibration import fit_homography, to_floor
from nestwatch_vision.pipeline import Pipeline
from nestwatch_vision.pose import Person
from nestwatch_vision.zones import ZoneCache

IMG = np.array([[100, 100], [500, 120], [560, 400], [60, 380]], float)      # MATH 1.5 camera and room (4 x 3 m)
FLOOR = np.array([[0, 0], [4, 0], [4, 3], [0, 3]], float)
H = fit_homography(IMG, FLOOR)
H_INV = np.linalg.inv(H)
NOW = datetime(2026, 10, 24, 12, 0)
DT = 1 / 8
ROW = {"id": "z_1", "name": "Stairs", "severity": "high", "status": "active", "escalation": "x",
       "polygon": [{"x": 2.8, "y": 1.9}, {"x": 4, "y": 1.9}, {"x": 4, "y": 3}, {"x": 2.8, "y": 3}],
       "schedule": {"named": None, "start_min": None, "end_min": None}}


def person_at(xy, rng, ankles=True):
    """A person whose feet are at floor position xy: their pixel comes from the inverse homography, plus 2 px of noise."""
    q = H_INV @ np.array([xy[0], xy[1], 1.0])
    u, v = q[:2] / q[2] + rng.normal(0, 2.0, 2)
    k = np.zeros((17, 3))
    if ankles:
        k[15], k[16] = (u - 5, v, 0.9), (u + 5, v, 0.9)
    return Person(np.array([u - 30, v - 150, u + 30, v + 5]), 0.9, k)


def make(zones=(ROW,), named=None, seed=0):
    cache = ZoneCache(named_schedules=named or {})
    cache.load(list(zones))
    return Pipeline(4.0, 3.0, H, cache, rng=np.random.default_rng(seed))


def walk(pipe, path, seconds, seed=0, start=0.0):
    rng = np.random.default_rng(seed)
    out = []
    for k in range(int(seconds / DT)):
        t = start + k * DT
        out.append((t, pipe.step([person_at(path(t), rng)], t, NOW)))
    return out


def test_a_standing_child_becomes_a_position_the_dashboard_can_draw():
    res = walk(make(), lambda t: (1.0, 1.0), 3.0)
    last = res[-1][1]
    assert len(last.positions) == 1
    p = last.positions[0]
    assert p["trackId"] == "t1" and p["kind"] == "child" and p["label"] == "1" and p["visible"] is True
    assert abs(p["x"] - 1.0) < 0.1 and abs(p["y"] - 1.0) < 0.1                     # the homography put them where they stand
    assert not any(r.events for _, r in res)                                      # nobody near the stairs: no alert


def test_a_child_walking_at_the_stairs_raises_exactly_one_early_alert():
    path = lambda t: (0.8 + 0.5 * t, 2.4)                                          # reaches the stairs edge (x = 2.8) at t = 4.0 s
    res = walk(make(), path, 7.0)
    events = [(t, e) for t, r in res for e in r.events]
    assert len(events) == 1                                                        # the 60 s cooldown stops repeats
    t, e = events[0]
    assert e.event_type == "zone_entry_predicted" and e.zone_id == "z_1" and e.severity == "high" and t < 4.0
    assert e.track_id == "t1" and e.clip_ref.startswith("evt_") and 0.0 < e.predicted_entry_s <= 3.0
    assert 4.0 - t >= 0.5                                                          # a usable warning (MATH 6.5: median 1.25 s)


def test_a_tagged_adult_is_reported_as_an_adult_and_never_triggers_an_alert():
    pipe = make()
    rng = np.random.default_rng(1)
    for k in range(10):
        pipe.step([person_at((1.0, 2.4), rng)], k * DT, NOW)
    assert pipe.tag_adult(1, "Maria") and not pipe.tag_adult(99, "Nobody")
    events = []
    for k in range(10, 70):                                                        # the adult walks straight into the stairs
        r = pipe.step([person_at((1.0 + 0.04 * (k - 10), 2.4), rng)], k * DT, NOW)
        events += r.events
    p = r.positions[0]
    assert p["kind"] == "adult" and p["label"] == "M" and not events


def test_a_foot_far_outside_the_room_is_ignored_not_tracked():
    pipe = make()
    rng = np.random.default_rng(2)
    r = pipe.step([person_at((9.0, 9.0), rng), person_at((1.0, 1.0), rng)], 0.0, NOW)
    assert r.skipped_out_of_room == 1 and r.detections == 1


def test_an_uncalibrated_camera_places_nobody():
    pipe = make()
    pipe.set_homography(None)
    r = pipe.step([person_at((1.0, 1.0), np.random.default_rng(3))], 0.0, NOW)
    assert r.positions == [] and r.events == []


def test_a_zone_that_is_off_by_schedule_does_not_alert():
    nap = {**ROW, "schedule": {"named": "nap_time", "start_min": None, "end_min": None}}
    pipe = make(zones=(nap,), named={"nap_time": (13 * 60, 14 * 60)})              # NOW is 12:00, outside the nap window
    res = walk(pipe, lambda t: (0.8 + 0.5 * t, 2.4), 7.0)
    assert not any(r.events for _, r in res)
    pipe2 = make(zones=(nap,), named={"nap_time": (11 * 60, 14 * 60)})             # inside the window: it alerts
    assert any(r.events for _, r in walk(pipe2, lambda t: (0.8 + 0.5 * t, 2.4), 7.0))


def test_a_child_already_in_the_zone_gets_an_entry_not_a_prediction():
    res = walk(make(), lambda t: (3.4, 2.4), 3.0)
    ev = [e for _, r in res for e in r.events]
    assert len(ev) == 1 and ev[0].event_type == "zone_entry" and ev[0].predicted_entry_s == 0.0


def test_four_children_and_two_zones_take_a_small_fraction_of_a_frame():
    zones = (ROW, {**ROW, "id": "z_2", "name": "Gate", "polygon": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 0.8}, {"x": 0, "y": 0.8}]})
    pipe = make(zones=zones)
    rng = np.random.default_rng(4)
    pts = [(0.6, 1.5), (1.5, 2.2), (2.0, 1.0), (1.2, 2.6)]
    for k in range(10):
        pipe.step([person_at(p, rng) for p in pts], k * DT, NOW)
    t0 = time.perf_counter()
    for k in range(10, 40):
        pipe.step([person_at(p, rng) for p in pts], k * DT, NOW)
    per_frame_ms = (time.perf_counter() - t0) / 30 * 1000
    assert per_frame_ms < 20                                                       # the budget is 125 ms at 8 Hz; pose takes 16 of it
