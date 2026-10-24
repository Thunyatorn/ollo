import math

import numpy as np

from nestwatch_vision.detectors.behaviour import BehaviourConfig, BehaviourDetector
from nestwatch_vision.pose import (L_ANKLE, L_HIP, L_SHOULDER, L_WRIST, NOSE, R_ANKLE, R_HIP, R_SHOULDER, R_WRIST, Person)

HZ = 12


def person(wrists=((80, 140), (120, 140)), ankles=((92, 220), (108, 220)), shift=(0.0, 0.0)):
    """A standing person about 70 px of torso tall; wrists and ankles can be placed or moved."""
    k = np.zeros((17, 3))
    pts = {NOSE: (100, 50), L_SHOULDER: (85, 80), R_SHOULDER: (115, 80), L_HIP: (90, 150), R_HIP: (110, 150),
           L_WRIST: wrists[0], R_WRIST: wrists[1], L_ANKLE: ankles[0], R_ANKLE: ankles[1]}
    for i, (u, v) in pts.items():
        k[i] = (u + shift[0], v + shift[1], 0.9)
    return Person(np.array([70 + shift[0], 40 + shift[1], 130 + shift[0], 225 + shift[1]]), 0.9, k)


def run(frames, seconds, hz=HZ, cfg=None, nap=False):
    det, out = BehaviourDetector(cfg), []
    for n in range(int(seconds * hz)):
        t = n / hz
        out += [(round(t, 2), e) for e in det.update([frames(t)], t, nap=nap)]
    return out


AT_THROAT = ((97, 70), (103, 70))


def test_both_hands_at_the_throat_alerts_after_about_a_second_and_a_half():
    ev = run(lambda t: person(wrists=AT_THROAT), 3.0)
    assert [e.kind for _, e in ev] == ["possible_distress"] and ev[0][1].severity == "high"
    assert 1.3 <= ev[0][0] <= 1.8


def test_one_hand_at_the_throat_or_hands_down_never_alerts():
    one = ((97, 70), (120, 140))
    assert run(lambda t: person(wrists=one), 10.0) == []
    assert run(lambda t: person(), 10.0) == []


def test_a_brief_touch_of_the_neck_does_not_alert():
    assert run(lambda t: person(wrists=AT_THROAT if t < 1.0 else ((80, 140), (120, 140))), 6.0) == []


def shaking(hz, amp_px):
    def frames(t):
        d = amp_px * math.sin(2 * math.pi * hz * t)
        return person(wrists=((80 + d, 140), (120 - d, 140)), ankles=((92 + d, 220), (108 - d, 220)))
    return frames


def test_limbs_shaking_at_3_hz_alert_after_several_seconds():
    ev = run(shaking(3.0, 14), 12.0)
    assert [e.kind for _, e in ev] == ["rhythmic_movement"]
    assert 6.0 <= ev[0][0] <= 10.0


def test_slow_waving_small_jitter_and_too_few_frames_do_not_alert():
    assert run(shaking(0.5, 14), 12.0) == []                        # 0.5 Hz: waving, not shaking
    assert run(shaking(3.0, 1.0), 12.0) == []                       # tiny: pose noise, not movement
    rng = np.random.default_rng(0)
    noisy = lambda t: person(wrists=((80 + rng.normal(0, 6), 140 + rng.normal(0, 6)), (120 + rng.normal(0, 6), 140)),
                             ankles=((92 + rng.normal(0, 6), 220), (108 + rng.normal(0, 6), 220)))
    assert run(noisy, 12.0) == []                                   # broadband noise has no single peak
    assert run(shaking(3.0, 14), 12.0, hz=5) == []                  # 5 frames a second cannot resolve 3 Hz


def test_walking_across_the_room_is_not_shaking():
    assert run(lambda t: person(shift=(25 * t, 0)), 12.0) == []      # steady drift is removed before the frequency check


def test_stillness_alerts_after_the_set_time_and_never_at_nap_time():
    cfg = BehaviourConfig(stillness_s=20.0)
    rng = np.random.default_rng(1)
    still = lambda t: person(shift=(rng.normal(0, 0.5), rng.normal(0, 0.5)))
    ev = run(still, 26.0, hz=4, cfg=cfg)
    assert [e.kind for _, e in ev] == ["stillness"] and ev[0][1].severity == "medium" and 20.0 <= ev[0][0] <= 23.0
    assert run(still, 26.0, hz=4, cfg=cfg, nap=True) == []


def test_moving_now_and_then_resets_stillness():
    cfg = BehaviourConfig(stillness_s=20.0)
    frames = lambda t: person(shift=(30.0 if int(t) % 15 == 14 else 0.0, 0))     # moves for one second every 15 s
    assert run(frames, 40.0, hz=4, cfg=cfg) == []


def test_pipeline_attaches_a_distress_alert_to_the_tracked_child():
    from datetime import datetime
    from tests.test_wiring import H_INV, make
    pipe, out = make(zones=()), []
    q = H_INV @ np.array([1.5, 1.5, 1.0]); u, v = q[:2] / q[2]                 # a child standing at (1.5, 1.5) m
    for n in range(int(3.0 * HZ)):
        t = n / HZ
        p = person(wrists=AT_THROAT, shift=(u - 100, v - 225))
        out += pipe.step([p], t, datetime(2026, 10, 24, 10, 0)).events
    kinds = [e.event_type for e in out]
    assert kinds == ["possible_distress"] and out[0].track_id != "t0" and out[0].severity == "high"
