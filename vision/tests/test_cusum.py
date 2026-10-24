import numpy as np
from nestwatch_vision.cusum import Cusum, CusumBank

DT = 1 / 8


def frames_to_fire(e, k=0.3, h=0.2, limit=800):
    c = Cusum(k, h)
    for i in range(1, limit):
        if c.update(e, DT, i * DT):
            return i
    return None


def test_single_frame_glitch_never_alerts():
    c = Cusum()
    fired = [c.update(1.0 if i == 10 else 0.0, DT, i * DT) for i in range(60)]
    assert not any(fired)
    c2 = Cusum()
    for i in range(11):
        c2.update(1.0 if i == 10 else 0.0, DT, i * DT)
    assert abs(c2.S - 0.0875) < 1e-9                              # MATH 7.4: far below h = 0.2


def test_two_frames_no_three_frames_yes():
    for n, expect in [(2, False), (3, True)]:                      # 0.175 then 0.2625 against h = 0.2
        c = Cusum()
        fired = [c.update(1.0, DT, i * DT) for i in range(n)]
        assert fired[-1] is expect


def test_time_to_alert_matches_the_math_md_table():
    for e, secs in [(1.0, 0.29), (0.85, 0.36), (0.70, 0.50), (0.52, 0.91), (0.40, 2.0)]:
        got = frames_to_fire(e) * DT
        assert secs - DT - 1e-9 <= got <= secs + DT + 1e-9, (e, got)  # within a frame of h / (e - k)
    assert frames_to_fire(0.30) is None and frames_to_fire(0.10) is None   # at or below the leak: never


def test_cooldown_and_reset():
    c = Cusum(cooldown=60)
    t = 0.0
    fires = []
    for i in range(1, 700):                                       # 87 s of constant danger
        t = i * DT
        if c.update(1.0, DT, t):
            fires.append(t)
    assert len(fires) == 2 and 59.9 < fires[1] - fires[0] < 61.0  # one alert per minute, not one per frame


def test_disarmed_zone_empties_the_bucket():
    c = Cusum()
    for i in range(2):
        c.update(1.0, DT, i * DT)
    assert abs(c.S - 0.175) < 1e-9
    c.update(1.0, DT, 2 * DT, armed=False)
    assert c.S == 0.0


def test_bank_keeps_separate_buckets_and_forgets_tracks():
    bank = CusumBank()
    for i in range(2):
        assert not bank.update((1, "stairs"), 1.0, i * DT)
        assert not bank.update((2, "stairs"), 0.0, i * DT)
    assert abs(bank.level((1, "stairs")) - 0.175) < 1e-9 and bank.level((2, "stairs")) == 0.0
    assert bank.update((1, "stairs"), 1.0, 2 * DT) is True        # third frame of full evidence fires
    assert bank.level((1, "stairs")) == 0.0                       # and empties the bucket
    bank.update((3, "stairs"), 1.0, 0.0)
    bank.forget_track(3)
    assert bank.level((3, "stairs")) == 0.0


def test_a_stalled_frame_cannot_alert_by_itself():
    """A pose-model hiccup (30 s gap) followed by one frame of full evidence must not fire: the gap counts for 0.15 s,
    so S = 0.7*0.125 + 0.7*0.15 = 0.1925, below the 0.2 threshold."""
    bank = CusumBank()
    bank.update((1, "z"), 1.0, 0.0)
    assert bank.update((1, "z"), 1.0, 30.0) is False
    assert abs(bank.level((1, "z")) - 0.1925) < 1e-9
