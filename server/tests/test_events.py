"""Event rules on synthetic skeletons: positives and look-alikes. Not accuracy on real footage."""
import asyncio
import base64
import math

import numpy as np
import pytest
from server.events import Cusum, EventDetector
from server.vision import VisionEngine

ASPECT = 16 / 9
H = 0.6  # Standing body height as a fraction of frame height.
# Standing pose offsets from (center x, head top), in body heights; COCO keypoint order.
STAND = [(0, .08), (-.02, .06), (.02, .06), (-.04, .07), (.04, .07), (-.12, .2), (.12, .2), (-.15, .35), (.15, .35),
         (-.16, .48), (.16, .48), (-.08, .52), (.08, .52), (-.08, .75), (.08, .75), (-.08, .98), (.08, .98)]


def skeleton(x0=0.8, top=0.2, lying=0.0, wrists=None, limb_shift=None, noise=0.0, rng=None):
    """Person dict in normalized coordinates. lying: 0 standing → 1 lying flat on the floor."""
    pts = np.array([(x0 + dx * H, top + dy * H) for dx, dy in STAND])
    if wrists == 'throat' or wrists == 'one':
        shoulders = (pts[5] + pts[6]) / 2
        throat = shoulders + 0.35 * (pts[0] - shoulders)
        pts[9] = throat + (-0.02 * H, 0)
        if wrists == 'throat':
            pts[10] = throat + (0.02 * H, 0)
    if limb_shift is not None:
        for i in (9, 10, 15, 16):
            pts[i] = pts[i] + (limb_shift * H, 0)
    if lying:
        pivot = np.array([x0, top + 0.98 * H])  # Rotate about the feet onto the floor.
        a = lying * math.pi / 2
        rot = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        pts = pivot + (pts - pivot) @ rot.T
    if noise:
        pts = pts + rng.normal(0, noise * H, pts.shape)
    return as_person(pts)


def as_person(pts):
    x1, y1 = pts.min(0) - 0.02
    x2, y2 = pts.max(0) + 0.02
    return {'x': x1 / ASPECT, 'y': y1, 'width': (x2 - x1) / ASPECT, 'height': y2 - y1, 'track_id': 1,
            'keypoints': [[float(x / ASPECT), float(y), 0.9] for x, y in pts]}


def crouched(k, hands=None, x0=0.8, top=0.2):
    """Facing the camera, compressed toward the floor to fraction k of standing height (torso stays upright in the image)."""
    pts = np.array([(x0 + dx * H, top + dy * H) for dx, dy in STAND])
    floor = top + 0.98 * H
    pts[:, 1] = floor - (floor - pts[:, 1]) * k
    if hands == 'floor':
        pts[9, 1] = pts[10, 1] = floor - 0.05 * H
    elif hands == 'lap':
        pts[9] = pts[10] = (pts[11] + pts[12]) / 2
    return as_person(pts)


def run(frames, fps, settings=None):
    """frames: callable t → person dict. Returns (time, kind) for each event."""
    detector = EventDetector(settings)
    events = []
    for n in range(int(frames[1] * fps)):
        t = n / fps
        for e in detector.update(1, frames[0](t), t * 1000, ASPECT):
            events.append((round(t, 2), e['kind']))
    return events, detector


def test_cusum_needs_sustained_evidence_and_respects_refractory():
    c = Cusum(k=0.45, h=0.8, refractory=15)
    fired = [t / 10 for t in range(40) if c.update(1.0, t / 10)]
    assert fired == [1.5]  # 0.8 / (1 − 0.45) ≈ 1.45 s, then refractory.
    c = Cusum(k=0.45, h=0.8)
    assert not any(c.update(0.4, t / 10) for t in range(200))  # Below k never accumulates.


def test_hands_at_throat_fires_once_and_ignores_look_alikes():
    events, _ = run((lambda t: skeleton(wrists='throat'), 4.0), fps=4)
    assert [k for _, k in events] == ['distress'] and 1.25 <= events[0][0] <= 2.0
    assert run((lambda t: skeleton(wrists='one'), 10.0), fps=4)[0] == []  # One hand: eating, scratching.
    assert run((lambda t: skeleton(wrists='throat' if t < 0.75 else None), 6.0), fps=4)[0] == []  # Brief.


def test_fall_requires_fast_drop_then_lying():
    fall = lambda t: skeleton(lying=0.0 if t < 3 else 1.0)
    events, _ = run((fall, 7.0), fps=4)
    assert [k for _, k in events] == ['fall'] and 4.0 <= events[0][0] <= 4.5
    slow = lambda t: skeleton(lying=min(max(t - 2, 0) / 5, 1.0))  # Deliberately lying down over 5 s.
    assert run((slow, 10.0), fps=4)[0] == []
    sit = lambda t: skeleton(top=0.2 if t < 3 else 0.35)  # Quick drop but torso stays upright.
    assert run((sit, 7.0), fps=4)[0] == []


def test_forward_fall_onto_hands_and_its_look_alikes():
    ramp = lambda t, start, span, low: 1.0 if t < start else max(low, 1.0 - (1.0 - low) * (t - start) / span)
    # Falls forward toward the camera: height collapses fast, hands reach the floor, stays down.
    fall = lambda t: crouched(ramp(t, 3.0, 0.5, 0.55), hands='floor' if t >= 3.3 else None)
    events, _ = run((fall, 9.0), fps=12)
    assert [k for _, k in events] == ['fall'] and 4.5 <= events[0][0] <= 5.5
    # Plops down to sit: just as fast and low, but upright with hands on the lap.
    sit = lambda t: crouched(ramp(t, 3.0, 0.4, 0.55), hands='lap' if t >= 3.2 else None)
    assert run((sit, 9.0), fps=12)[0] == []
    # Crouches to pick something up, hands to the floor, and stands back up within 1.5 s.
    crouch = lambda t: crouched(ramp(t, 3.0, 0.4, 0.6) if t < 4.2 else min(1.0, 0.6 + (t - 4.2)), hands='floor' if 3.2 <= t < 4.2 else None)
    assert run((crouch, 9.0), fps=12)[0] == []


def test_rhythmic_movement_needs_band_power_amplitude_and_frame_rate():
    shake = lambda t: skeleton(limb_shift=0.05 * math.sin(2 * math.pi * 3 * t))
    events, detector = run((shake, 14.0), fps=15)
    assert 'rhythmic' in [k for _, k in events]
    assert detector.status()['rhythmic'] == 'active'
    events, detector = run((shake, 14.0), fps=2)
    assert events == [] and detector.status()['rhythmic'].startswith('needs')
    for slow in (0.4, 0.6, 0.8):  # Slow waving, including just below the band edge.
        wave = lambda t: skeleton(limb_shift=0.1 * math.sin(2 * math.pi * slow * t))
        assert run((wave, 14.0), fps=15)[0] == []
    jerks = lambda t: skeleton(limb_shift=0.05 * np.sign(math.sin(2 * math.pi * 2 * t)) * abs(math.sin(2 * math.pi * 2 * t)) ** 0.3)
    assert 'rhythmic' in [k for _, k in run((jerks, 14.0), fps=15)[0]]  # Jerky, non-sinusoidal rhythm.
    rng = np.random.default_rng(0)
    for level in (0.003, 0.02, 0.03):  # Pose-estimator jitter on a still person, up to 3% of body height.
        jitter = lambda t: skeleton(noise=level, rng=rng)
        assert 'rhythmic' not in [k for _, k in run((jitter, 30.0), fps=15)[0]]


def test_stillness_duration_motion_and_nap_mode():
    rng = np.random.default_rng(1)
    still = lambda t: skeleton(noise=0.002, rng=rng)
    events, _ = run((still, 14.0), fps=4, settings={'stillness_seconds': 10})
    assert [k for _, k in events] == ['stillness'] and 10 <= events[0][0] <= 12.5
    walk = lambda t: skeleton(x0=0.3 + 0.1 * t)
    assert run((walk, 14.0), fps=4, settings={'stillness_seconds': 10})[0] == []
    assert run((still, 14.0), fps=4, settings={'stillness_seconds': 10, 'nap_mode': True})[0] == []


def test_engine_turns_local_rule_into_observation():
    import cv2
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    image = base64.b64encode(raw).decode()
    engine = VisionEngine()
    engine._detect = lambda _: ([skeleton(wrists='throat')], 'active')
    async def scenario():
        found = []
        for seq in range(10):
            result = await engine.process_frame(dict(session_id='s1', epoch=1, frame_seq=seq, media_time_ms=seq * 250, image=image))
            found += result['observations']
        return found, result
    found, result = asyncio.run(scenario())
    assert [(o['kind'], o['origin'], o['priority']) for o in found] == [('distress', 'local_rule', 'critical')]
    assert found[0]['observations'][0].startswith('Person 1:')
    assert result['detectors']['rhythmic'].startswith('needs')
