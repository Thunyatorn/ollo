import numpy as np

from nestwatch_vision.detectors.not_visible import NotVisibleConfig, NotVisibleDetector
from nestwatch_vision.tracker import LostTrack
from tests.test_wiring import DT, NOW, make, person_at


# ---- the detector on its own ----
def lost(id=1, tag=None, at=10.0, pos=(1.0, 1.0)):
    return LostTrack(id, np.array(pos), tag, at)


def run(det, newly, remembered, children, ages, t):
    return det.update(newly, remembered, children, ages, t)


def test_reports_a_lost_child_once_the_grace_period_has_passed():
    det, l = NotVisibleDetector(), lost()
    assert run(det, [l], [l], [], {1: 20.0}, 10.0) == []
    assert run(det, [], [l], [], {1: 20.0}, 10.9) == []
    assert run(det, [], [l], [], {1: 20.0}, 11.0) == [l]
    assert run(det, [], [l], [], {1: 20.0}, 12.0) == []                      # once only


def test_a_child_found_again_under_the_same_identity_is_cancelled():
    det, l = NotVisibleDetector(), lost()
    run(det, [l], [l], [], {1: 20.0}, 10.0)
    assert run(det, [], [], [], {1: 20.0}, 11.5) == []                       # the tracker no longer remembers it as lost


def test_adults_flickers_and_children_with_someone_still_there_are_not_reported():
    det = NotVisibleDetector()
    adult, flicker, twin = lost(1, tag="Maria"), lost(2), lost(3, pos=(2.0, 2.0))
    ages = {1: 30.0, 2: 1.0, 3: 30.0}
    run(det, [adult, flicker, twin], [adult, flicker, twin], [np.array([2.4, 2.0])], ages, 10.0)
    assert run(det, [], [adult, flicker, twin], [np.array([2.4, 2.0])], ages, 11.5) == []   # 0.4 m from where child 3 was seen


def test_a_child_with_another_child_far_away_is_still_reported():
    det, l = NotVisibleDetector(NotVisibleConfig(near_m=1.0)), lost(pos=(0.5, 0.5))
    run(det, [l], [l], [np.array([3.0, 2.5])], {1: 20.0}, 10.0)
    assert run(det, [], [l], [np.array([3.0, 2.5])], {1: 20.0}, 11.2) == [l]


# ---- through the whole pipeline, with a made-up child ----
def events_for(present, seconds=14.0, seed=3):
    """A child standing at (1, 1) while present(t) is true; returns [(t, event)] for the whole run."""
    pipe, rng, out = make(zones=()), np.random.default_rng(seed), []
    for k in range(int(seconds / DT)):
        t = k * DT
        people = [person_at((1.0, 1.0), rng)] if present(t) else []
        out += [(t, e) for e in pipe.step(people, t, NOW).events]
    return out


def test_a_child_who_vanishes_for_good_raises_one_low_alert_a_few_seconds_later():
    ev = events_for(lambda t: t < 6.0)
    assert len(ev) == 1
    t, e = ev[0]
    assert e.event_type == "child_not_visible" and e.severity == "low" and e.track_id == "t1" and e.zone_id == ""
    assert 8.5 <= t <= 9.5                                                    # 6 s + 2 s tracker timeout + 1 s grace


def test_a_child_hidden_for_a_moment_raises_nothing():
    assert events_for(lambda t: t < 6.0 or t > 8.2) == []                    # back after 2.2 s


def test_a_child_who_was_never_really_there_raises_nothing():
    assert events_for(lambda t: 4.0 <= t < 5.0) == []                         # one second of detections: under min_age_s
