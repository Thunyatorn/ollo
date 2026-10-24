from datetime import datetime
import numpy as np
from nestwatch_vision.geometry import distance_to_polygon, points_in_polygon
from nestwatch_vision.zones import Zone, ZoneCache

ROW = {"id": "z_1", "name": "Stairs", "severity": "high", "status": "active", "escalation": "buzzer_then_call",
       "polygon": [{"x": 2.8, "y": 1.9}, {"x": 4, "y": 1.9}, {"x": 4, "y": 3}, {"x": 2.8, "y": 3}],
       "schedule": {"named": None, "startMin": None, "endMin": None}}
NOON, NIGHT = datetime(2026, 10, 24, 12, 0), datetime(2026, 10, 24, 23, 30)
NAMED = {"nap_time": (12 * 60 + 30, 14 * 60)}


def test_padding_makes_the_zone_two_centimeters_bigger():
    z = Zone.from_row(ROW)
    assert points_in_polygon((2.79, 2.4), z.polygon)               # 1 cm outside the drawn edge is now inside
    assert not points_in_polygon((2.77, 2.4), z.polygon)
    assert abs(distance_to_polygon((2.8, 2.4), z.polygon) - 0.02) < 1e-9


def test_always_on_without_a_schedule_and_off_when_not_active():
    assert Zone.from_row(ROW).active_at(NOON, NAMED)
    assert not Zone.from_row({**ROW, "status": "off"}).active_at(NOON, NAMED)
    assert not Zone.from_row({**ROW, "status": "draft"}).active_at(NOON, NAMED)


def test_explicit_hours_and_wrap_past_midnight():
    day = Zone.from_row({**ROW, "schedule": {"startMin": {"some": 9 * 60}, "endMin": {"some": 17 * 60}}})
    assert day.active_at(NOON, NAMED) and not day.active_at(NIGHT, NAMED)
    overnight = Zone.from_row({**ROW, "schedule": {"startMin": {"some": 22 * 60}, "endMin": {"some": 6 * 60}}})
    assert overnight.active_at(NIGHT, NAMED) and not overnight.active_at(NOON, NAMED)
    assert overnight.active_at(datetime(2026, 10, 24, 3, 0), NAMED)


def test_named_schedule_resolves_and_unknown_name_stays_quiet():
    nap = Zone.from_row({**ROW, "schedule": {"named": {"some": "nap_time"}}})
    assert nap.active_at(datetime(2026, 10, 24, 13, 0), NAMED) and not nap.active_at(NOON, NAMED)
    assert not nap.active_at(NOON, {})                             # unknown name: do not guess


def test_cache_returns_only_zones_in_force():
    cache = ZoneCache(named_schedules=NAMED)
    cache.load([ROW, {**ROW, "id": "z_2", "status": "off"}, {**ROW, "id": "z_3", "schedule": {"named": {"some": "nap_time"}}}])
    assert [z.id for z in cache.active(NOON)] == ["z_1"]
    assert [z.id for z in cache.active(datetime(2026, 10, 24, 13, 0))] == ["z_1", "z_3"]
