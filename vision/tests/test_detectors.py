"""Fall and unsupervised detection inside the pipeline, with made-up people."""
from datetime import datetime
import numpy as np
from nestwatch_vision.detectors.fall import FallDetector
from nestwatch_vision.detectors.unsupervised import UnsupervisedConfig, evidence
from nestwatch_vision.pipeline import Pipeline
from nestwatch_vision.pose import Person
from nestwatch_vision.zones import ZoneCache
from tests.test_wiring import H, NOW, person_at

DT = 1 / 12


def body(cx, bottom, w, h, lying=False, conf=0.9):
    """A person box with shoulder and hip keypoints, upright or lying."""
    k = np.zeros((17, 3))
    if lying:
        k[5], k[6], k[11], k[12] = (cx - 0.4 * w, bottom - h / 2, .9), (cx - 0.4 * w, bottom - h / 2, .9), (cx + 0.2 * w, bottom - h / 2, .9), (cx + 0.2 * w, bottom - h / 2, .9)
    else:
        k[5], k[6], k[11], k[12] = (cx - 8, bottom - 0.8 * h, .9), (cx + 8, bottom - 0.8 * h, .9), (cx - 6, bottom - 0.45 * h, .9), (cx + 6, bottom - 0.45 * h, .9)
    return Person(np.array([cx - w / 2, bottom - h, cx + w / 2, bottom], float), conf, k)


def frames(script, seconds):
    """script(t) -> Person; returns the list of (t, [Person])."""
    return [(i * DT, [script(i * DT)]) for i in range(int(seconds / DT))]


def falls(seq):
    d, out = FallDetector(), []
    for t, ppl in seq:
        out += [(t, e) for e in d.update(ppl, t)]
    return out


def fall_script(t):
    if t < 2.0:
        return body(300, 400, 60, 200)                            # standing
    if t < 2.5:
        a = (t - 2.0) / 0.5                                       # falling: half a second
        return body(300 + 40 * a, 400, 60 + 140 * a, 200 - 140 * a, lying=a > 0.5)
    return body(340, 400, 200, 60, lying=True, conf=0.3)          # on the floor, the model is less sure


def test_a_fast_drop_to_the_floor_is_one_fall():
    got = falls(frames(fall_script, 6.0))
    assert len(got) == 1 and 2.5 < got[0][0] < 4.0                  # once, about a second after landing


def test_sitting_down_is_not_a_fall():
    def sit(t):
        a = min(max((t - 2.0) / 0.6, 0), 1)                       # sits onto a chair or bed
        return body(300, 400 - 30 * a, 60 + 20 * a, 200 - 70 * a)  # shorter and a bit wider, still upright
    assert falls(frames(sit, 6.0)) == []


def test_lying_down_slowly_is_not_a_fall():
    def lie(t):
        a = min(max((t - 1.0) / 4.0, 0), 1)                       # four seconds to lie down on purpose
        return body(300, 400, 60 + 140 * a, 200 - 140 * a, lying=a > 0.5)
    assert falls(frames(lie, 8.0)) == []


def test_a_short_dropout_on_the_floor_does_not_reset_and_a_fall_fires_once():
    seq = frames(fall_script, 6.0)
    seq = [(t, [] if 2.7 < t < 3.0 else p) for t, p in seq]      # the model loses the person for 0.3 s
    assert len(falls(seq)) == 1


# ---- in the pipeline ---------------------------------------------------------------------------
def pipe():
    return Pipeline(4.0, 3.0, H, ZoneCache(), rng=np.random.default_rng(0))


def test_a_fall_becomes_a_high_event_for_that_child():
    p = pipe()
    ev = []
    for t, ppl in frames(fall_script, 6.0):
        ev += p.step(ppl, t, NOW).events
    f = [e for e in ev if e.event_type == "fall"]
    assert len(f) == 1 and f[0].severity == "high" and f[0].track_id == "t1" and f[0].zone_id == ""


def test_a_tagged_adult_falling_is_not_reported_as_a_childs_fall():
    p = pipe()
    seq = frames(fall_script, 6.0)
    for t, ppl in seq[:12]:
        p.step(ppl, t, NOW)
    assert p.tag_adult(1, "Maria")
    ev = [e for t, ppl in seq[12:] for e in p.step(ppl, t, NOW).events]
    assert not [e for e in ev if e.event_type == "fall"]


def test_unsupervised_evidence_shape():
    cfg = UnsupervisedConfig()
    assert evidence((0, 0), [], cfg) == 1.0                                   # no adult in view
    assert evidence((0, 0), [(0.5, 0)], cfg) < 0.03                          # adult half a meter away
    assert abs(evidence((0, 0), [(2.0, 0)], cfg) - 0.5) < 1e-9               # exactly at R
    assert evidence((0, 0), [(3.5, 0)], cfg) > 0.97


def run_room(p, child_at, adult_at, seconds, start=0.0):
    rng, ev = np.random.default_rng(3), []
    for k in range(int(seconds / (1 / 8))):
        t = start + k / 8
        ppl = [person_at(child_at(t), rng)] + ([person_at(adult_at(t), rng)] if adult_at(t) is not None else [])
        ev += [e for e in p.step(ppl, t, NOW).events if e.event_type == "unsupervised"]
    return ev


def test_unsupervised_stays_off_until_someone_is_tagged_as_an_adult():
    p = pipe()
    assert run_room(p, lambda t: (0.5, 1.5), lambda t: None, 30.0) == []    # a lone person, nobody tagged: no alert


def test_a_child_far_from_the_tagged_adult_alerts_after_about_ten_seconds_and_a_close_one_never():
    p = pipe()
    run_room(p, lambda t: (0.6, 2.4), lambda t: (3.5, 0.6), 1.0)           # two people appear (tracks 1 = child, 2 = adult)
    adult = [tr for tr in p.tracker.tracks if tr.pos[0] > 2.0][0]
    assert p.tag_adult(adult.id, "Maria")
    ev = run_room(p, lambda t: (0.6, 2.4), lambda t: (3.5, 0.6), 20.0, start=1.0)
    assert len(ev) == 1 and ev[0].severity == "medium" and 9.0 < ev[0].at - 1.0 < 16.0    # about h / (e - k) = 10 to 12 s
    p2 = pipe()
    run_room(p2, lambda t: (1.0, 1.5), lambda t: (2.0, 1.5), 1.0)
    p2.tag_adult([tr for tr in p2.tracker.tracks if tr.pos[0] > 1.5][0].id, "Maria")
    assert run_room(p2, lambda t: (1.0, 1.5), lambda t: (2.0, 1.5), 30.0, start=1.0) == []   # adult 1 m away: fine
