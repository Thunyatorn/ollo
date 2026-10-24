"""DET-9 predictive zone warning: calibration, Kalman, entry probability, synthetic acceptance cases."""
import asyncio
import base64
import os
import tempfile

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='lookout-test-'))

import numpy as np
import pytest
from server.predict import ApproachMonitor, Calibration, KalmanCV, entry_probability
from server.vision import VisionEngine

# Floor → normalized image for a camera looking down at a 4 m × 4 m area (a perspective, not affine, map).
G = np.array([[0.20, 0.03, 0.10], [0.00, 0.12, 0.20], [0.00, 0.06, 1.00]])
# Simple top-down map for behavior tests: image (0..1) ↔ an 8 m × 8 m floor.
TOP = [{'image': [u, v], 'floor': [8 * u, 8 * v]} for u, v in ((0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9))]
ZONE = [[0.5, 0.25], [0.75, 0.25], [0.75, 0.75], [0.5, 0.75]]  # Floor x 4–6 m, y 2–6 m.


def project(floor_xy):
    p = G @ np.array([*floor_xy, 1.0])
    return [float(p[0] / p[2]), float(p[1] / p[2])]


def test_calibration_fits_and_rejects_bad_points():
    floor = [(0, 0), (4, 0), (4, 4), (0, 4)]
    cal = Calibration.fit([{'image': project(f), 'floor': list(f)} for f in floor])
    assert cal.error_m < 0.01
    assert np.allclose(cal.to_floor(project((1.5, 2.5))), (1.5, 2.5), atol=0.01)
    assert np.allclose(cal.to_image((1.5, 2.5)), project((1.5, 2.5)), atol=1e-4)
    assert Calibration.from_dict(cal.as_dict()).to_floor(project((3, 1))) == pytest.approx((3, 1), abs=0.01)
    # Six or more points: RANSAC ignores one wrong click, and reports it.
    six = [(0, 0), (4, 0), (4, 4), (0, 4), (2, 1), (1, 3)]
    points = [{'image': project(f), 'floor': list(f)} for f in six]
    points[4]['floor'] = [3.5, 3.0]  # Typo of about 2.5 m.
    robust = Calibration.fit(points)
    assert robust.ignored == [4] and robust.error_m < 0.05
    bad = {
        'too few': [{'image': project(f), 'floor': list(f)} for f in floor[:3]],
        'duplicate': [{'image': project(f), 'floor': list(f)} for f in [floor[0], floor[0], floor[1], floor[2]]],
        'collinear': [{'image': project((x, 0)), 'floor': [x, 0]} for x in (0, 1, 2, 3)],
        'out of range': [{'image': [1.5, 0.5], 'floor': [0, 0]}] + [{'image': project(f), 'floor': list(f)} for f in floor[1:]],
        'inconsistent': [{'image': project(f), 'floor': list(f)} for f in floor] + [{'image': project((2, 2)), 'floor': [2.6, 2.0]}],
    }
    for name, pts in bad.items():
        with pytest.raises(ValueError):
            Calibration.fit(pts)


def test_jacobian_matches_finite_difference():
    cal = Calibration.fit([{'image': project(f), 'floor': list(f)} for f in [(0, 0), (4, 0), (4, 4), (0, 4)]])
    uv, eps = np.array(project((2, 2))), 1e-5
    numeric = np.column_stack([(cal.to_floor(uv + d) - cal.to_floor(uv - d)) / (2 * eps) for d in (np.array([eps, 0]), np.array([0, eps]))])
    assert np.allclose(cal.jacobian(uv), numeric, rtol=1e-4)


def test_entry_probability_geometry():
    zone = [(2, 0), (3, 0), (3, 1), (2, 1)]
    tight = np.eye(2) * 1e-4
    rng = np.random.default_rng(0)
    p, eta = entry_probability((0, 0.5), (1, 0), tight, zone, rng=rng)
    assert p == 1.0 and eta == pytest.approx(2.0, abs=0.05)
    assert entry_probability((0, 0.5), (-1, 0), tight, zone, rng=rng)[0] == 0.0  # Walking away.
    assert entry_probability((0, 0.5), (0.2, 0), tight, zone, rng=rng)[0] == 0.0  # Would arrive after τ.
    assert entry_probability((0, 2.0), (1, 0), tight, zone, rng=rng)[0] == 0.0  # Passes beside the zone.
    assert entry_probability((2.5, 0.5), (0, 0), tight, zone, rng=rng) == (1.0, 0.0)  # Already inside.
    half = entry_probability((0, 0.5), (1, 0), np.diag([1e-4, 1.0]), [(2, 0.5), (3, 0.5), (3, 3), (2, 3)], rng=rng)[0]
    assert 0.3 < half < 0.7  # Uncertain heading toward a zone covering half the directions.


def kalman_track(points, fps=12):
    kf = None
    for n, z in enumerate(points):
        R = np.eye(2) * 0.03 ** 2
        kf = KalmanCV(np.array(z), R, n / fps) if kf is None else kf
        kf.step(np.array(z), R, n / fps)
    return kf


def test_kalman_recovers_walking_velocity():
    rng = np.random.default_rng(1)
    kf = kalman_track([(t / 12 * 1.0 + rng.normal(0, 0.03), 1 + rng.normal(0, 0.03)) for t in range(24)])
    assert np.allclose(kf.velocity, (1.0, 0.0), atol=0.15)


def simulate(path, seconds=6.0, fps=12, noise=0.03, seed=0):
    """Feed a floor-meter path through the top-down calibration; return (first warning time, entry time, statuses)."""
    rng = np.random.default_rng(seed)
    cal, monitor = Calibration.fit(TOP), ApproachMonitor()
    zone = cal.zone_to_floor(ZONE)
    first_warning, entry = None, None
    for n in range(int(seconds * fps)):
        t = n / fps
        x, y = path(t)
        uv = ((x + rng.normal(0, noise)) / 8, (y + rng.normal(0, noise)) / 8)
        status = monitor.update(7, uv, t, cal, zone)
        if status['started'] and first_warning is None:
            first_warning = t
        if entry is None and 4.0 <= x <= 6.0 and 2.0 <= y <= 6.0:
            entry = t
    return first_warning, entry


def test_approach_warns_early_and_ignores_look_alikes():
    for seed in range(5):
        warned, entered = simulate(lambda t: (0.0 + 1.0 * t, 4.0), seed=seed)  # Straight at 1 m/s from 4 m away.
        assert entered == pytest.approx(4.0, abs=0.1) and warned is not None and entered - warned >= 2.0
        assert simulate(lambda t: (1.0 + 1.0 * t, 1.5), seed=seed)[0] is None  # Parallel, 0.5 m from the edge.
        assert simulate(lambda t: (3.0, 4.0), noise=0.05, seed=seed)[0] is None  # Standing 1 m away, 5 cm jitter.


def test_engine_warns_without_creating_an_incident():
    import cv2
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    image = base64.b64encode(raw).decode()
    cal = Calibration.fit(TOP)
    engine = VisionEngine({'zone': {'enabled': True, 'vertices': ZONE}, 'calibration': cal.as_dict()})
    assert engine.events.status() is not None and engine._result([], [])['detectors']['predictive'] == 'active'
    def person(t):
        u = min(1.0 * t, 5.0) / 8  # Walks 1 m/s toward the zone and into it.
        keypoints = [[0.0, 0.0, 0.0]] * 17
        keypoints[15] = keypoints[16] = [u, 0.5, 0.9]
        return {'x': u - 0.03, 'y': 0.3, 'width': 0.06, 'height': 0.2, 'confidence': 0.9, 'track_id': 3, 'keypoints': keypoints}
    async def scenario():
        found, warned_overlay = [], None
        for seq in range(72):
            t = seq / 12
            engine._detect = lambda _, t=t: ([person(t)], 'active')
            result = await engine.process_frame(dict(session_id='s1', epoch=1, frame_seq=seq, media_time_ms=t * 1000, image=image))
            found += [(round(t, 2), o['kind'], o['priority']) for o in result['observations']]
            if result['overlays'] and result['overlays'][0].get('approach', {}).get('warning') and warned_overlay is None:
                warned_overlay = result['overlays'][0]['approach']
        return found, warned_overlay
    found, overlay = asyncio.run(scenario())
    kinds = [k for _, k, _ in found]
    assert kinds.count('approach') == 1 and kinds.index('approach') < kinds.index('boundary')
    approach = next(f for f in found if f[1] == 'approach')
    assert approach[2] == 'medium'
    assert overlay['p'] > 0.5 and 0 < overlay['eta_s'] <= 3.0 and len(overlay['path']) == 2
    uncalibrated = VisionEngine({'zone': {'enabled': True, 'vertices': ZONE}})
    assert uncalibrated._result([], [])['detectors']['predictive'] == 'needs calibration'


def test_state_exposes_floor_plan():
    from fastapi.testclient import TestClient
    import server.app as api
    with TestClient(api.app) as client:
        client.get('/api/state')
        settings = api.store.get('settings')
        settings['zone'] = {'enabled': True, 'vertices': ZONE}
        api.store.put('settings', settings)
        state = client.post('/api/calibration', json={'points': TOP}).json()
        plan = state['floor_plan']
        assert [p for p in plan['points']] == [p['floor'] for p in TOP]
        default = next(z for z in plan['zones'] if z['id'] == 'default')
        assert np.allclose(default['polygon'], [[8 * u, 8 * v] for u, v in ZONE], atol=0.01)
        assert client.delete('/api/calibration').json()['floor_plan'] is None
    # Engine overlays carry floor positions and, while warned, the predicted floor path.
    import cv2
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    engine = VisionEngine({'zone': {'enabled': True, 'vertices': ZONE}, 'calibration': Calibration.fit(TOP).as_dict()})
    def person(t):
        u = 1.0 * t / 8
        keypoints = [[0.0, 0.0, 0.0]] * 17
        keypoints[15] = keypoints[16] = [u, 0.5, 0.9]
        return {'x': u - 0.03, 'y': 0.3, 'width': 0.06, 'height': 0.2, 'confidence': 0.9, 'track_id': 4, 'keypoints': keypoints}
    async def scenario():
        last = None
        for seq in range(30):
            engine._detect = lambda _, t=seq / 12: ([person(t)], 'active')
            last = await engine.process_frame(dict(session_id='s1', epoch=1, frame_seq=seq, media_time_ms=seq / 12 * 1000, image=base64.b64encode(raw).decode()))
        return last['overlays'][0]
    overlay = asyncio.run(scenario())
    assert overlay['floor'] == pytest.approx([29 / 12, 4.0], abs=0.02)
    assert overlay['approach']['warning'] and len(overlay['approach']['floor_path']) == 2
