import os
import numpy as np
import pytest
from nestwatch_vision import pose
from nestwatch_vision.pose import OneEuro, Person, dedupe, foot_point

KP = lambda **over: np.array([[*over.get(str(i), (0, 0, 0))] for i in range(17)], float)


def person(**kp):
    return Person(np.array([100.0, 50.0, 200.0, 400.0]), 0.9, KP(**kp))


def test_foot_point_prefers_two_ankles_then_one_then_the_box_bottom():
    both = person(**{"15": (120, 380, 0.9), "16": (180, 384, 0.8)})
    f = foot_point(both)
    assert (f.u, f.v, f.quality) == (150.0, 382.0, "ankles")
    one = person(**{"16": (180, 384, 0.8)})
    f = foot_point(one)
    assert (f.u, f.v, f.quality) == (180.0, 384.0, "one_ankle")
    none = person(**{"15": (120, 380, 0.1)})                          # below the 0.3 floor: treated as missing, not as a point
    f = foot_point(none)
    assert (f.u, f.v, f.quality) == (150.0, 400.0, "box_bottom")


def test_low_confidence_keypoints_are_missing_not_zero():
    p = person(**{"5": (130, 120, 0.9), "6": (170, 120, 0.2)})
    assert p.kp(5) == (130.0, 120.0) and p.kp(6) is None and p.mid(5, 6) is None


def test_torso_length_is_shoulder_to_hip_midpoint():
    p = person(**{"5": (130, 100, .9), "6": (170, 100, .9), "11": (135, 220, .9), "12": (165, 220, .9)})
    assert p.torso_length == pytest.approx(120.0)
    assert person().torso_length is None


def test_one_euro_smooths_a_still_point_and_follows_a_fast_one():
    rng = np.random.default_rng(0)
    f, out, raw = OneEuro(), [], []
    for i in range(200):                                              # standing still, 2 px of jitter, 30 fps
        x = 100 + rng.normal(0, 2.0, 2)
        raw.append(x); out.append(f(x, i / 30))
    assert np.std(np.array(out)[50:], axis=0).mean() < 0.5 * np.std(np.array(raw)[50:], axis=0).mean()
    f, lag = OneEuro(), []
    for i in range(90):                                               # moving 300 px/s: it must not lag far behind
        truth = np.array([10 + 10.0 * i, 50.0])
        lag.append(np.linalg.norm(f(truth, i / 30) - truth))
    assert np.mean(lag[30:]) < 8.0                                    # under a third of a frame at that speed


def box_person(x1, y1, x2, y2, conf):
    return Person(np.array([x1, y1, x2, y2], float), conf, KP())


def test_dedupe_removes_the_weaker_duplicate_but_keeps_neighbours_and_a_child_in_front_of_an_adult():
    # the real duplicate from the nano model on the sample photo: IoU 0.68
    dup = dedupe([box_person(0, 446, 64, 906, 0.39), box_person(0, 521, 77, 883, 0.35)])
    assert len(dup) == 1 and dup[0].box_conf == 0.39
    # two people side by side (IoU 0.08, as in the photo)
    assert len(dedupe([box_person(49, 396, 239, 907, 0.86), box_person(224, 404, 346, 866, 0.84)])) == 2
    # a small child standing right in front of an adult: fully inside the adult's box, but IoU only about 0.25
    adult, child = box_person(100, 100, 300, 500, 0.9), box_person(160, 300, 240, 500, 0.8)
    assert len(dedupe([adult, child])) == 2


WEIGHTS = os.path.join(os.path.dirname(__file__), "..", "..", "weights", "yolo26n-pose.pt")   # the nano model is the one that duplicated


@pytest.mark.skipif(not os.path.exists(WEIGHTS), reason="pose weights not downloaded")
def test_model_finds_the_people_in_the_sample_photo():
    import cv2, ultralytics
    from nestwatch_vision.config import PoseConfig
    img = cv2.imread(os.path.join(os.path.dirname(ultralytics.__file__), "assets", "bus.jpg"))
    people = pose.PoseModel(PoseConfig(weights=WEIGHTS, device="cpu")).infer(img)
    assert len(people) == 4                                           # four people by the bus; the nano model's duplicate is removed
    assert all(p.kpts.shape == (17, 3) and p.box.shape == (4,) for p in people)
    feet = [foot_point(p) for p in people]
    assert any(f.quality == "ankles" for f in feet)
    h, w = img.shape[:2]
    assert all(0 <= f.u <= w and 0 <= f.v <= h + 5 for f in feet)
