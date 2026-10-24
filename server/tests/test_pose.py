"""Multi-person tracking rules with injected tracks; not detection accuracy."""
import asyncio
import base64
import os

import pytest
from server.vision import MODELS_DIR, POSE_MODEL, TRACK_TIMEOUT_MS, VisionEngine, foot_point


SQUARE = [(0.5, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.9)]


def person(tid, x, ankle_conf=0.9):
    keypoints = [[0.0, 0.0, 0.0]] * 17
    keypoints[15] = [x + 0.03, 0.48, ankle_conf]
    keypoints[16] = [x + 0.07, 0.50, ankle_conf]
    return {'x': x, 'y': 0.2, 'width': 0.1, 'height': 0.4, 'confidence': 0.9, 'track_id': tid, 'keypoints': keypoints}


def blank_frame():
    import cv2
    import numpy as np
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    return base64.b64encode(raw).decode()


def test_foot_point_prefers_confident_ankles():
    # Ankles give the horizontal position; the box bottom (where soles touch the floor) gives the vertical.
    assert foot_point({**person(1, 0.2), 'width': 0.2}) == pytest.approx((0.25, 0.60))
    # Hidden feet (sitting, crawling, occluded) fall back to the box's bottom center.
    assert foot_point({**person(1, 0.2, ankle_conf=0.1), 'width': 0.2}) == pytest.approx((0.30, 0.60))
    # Box cut off by the frame edge but ankles visible: the ankles give the vertical position too.
    assert foot_point({**person(1, 0.2), 'y': 0.5, 'height': 0.5}) == pytest.approx((0.25, 0.50))
    # Feet cut off by the frame edge: ground position unknown, not "outside".
    cut = {**person(1, 0.2, ankle_conf=0.1), 'y': 0.5, 'height': 0.5}
    assert foot_point(cut) is None


def test_each_tracked_person_has_own_zone_state():
    engine = VisionEngine({'zone': {'vertices': SQUARE}})
    image = blank_frame()
    people = {'value': []}
    engine._detect = lambda _: (people['value'], 'active')
    def frame(seq):
        return dict(session_id='s1', epoch=1, frame_seq=seq, media_time_ms=seq * 250, image=image)
    async def scenario():
        people['value'] = [person(1, 0.1), person(2, 0.2)]
        for i in range(3):
            result = await engine.process_frame(frame(i))
            assert not result['observations']
        assert {o['id'] for o in result['overlays']} == {'person-1', 'person-2'}
        people['value'] = [person(1, 0.6), person(2, 0.2)]
        for i in range(3, 5):
            assert not (await engine.process_frame(frame(i)))['observations']
        result = await engine.process_frame(frame(5))
        assert [o['track_id'] for o in result['observations']] == ['person-1']
        assert {o['id']: o['in_zone'] for o in result['overlays']} == {'person-1': True, 'person-2': False}
    asyncio.run(scenario())


def test_missing_track_is_unknown_then_forgotten():
    engine = VisionEngine({'zone': {'vertices': SQUARE}})
    image = blank_frame()
    people = {'value': [person(7, 0.6)]}
    engine._detect = lambda _: (people['value'], 'active')
    def frame(seq, t):
        return dict(session_id='s1', epoch=1, frame_seq=seq, media_time_ms=t, image=image)
    async def scenario():
        for i in range(3):
            await engine.process_frame(frame(i, i * 250))
        assert engine.zones[(7, 'default')].state is True
        people['value'] = []
        await engine.process_frame(frame(3, 1000))
        assert engine.zones[(7, 'default')].count == 0
        await engine.process_frame(frame(4, 500 + TRACK_TIMEOUT_MS + 100))
        assert not any(key[0] == 7 for key in engine.zones)
    asyncio.run(scenario())


@pytest.mark.skipif(not (MODELS_DIR / POSE_MODEL).is_file() or os.getenv('LOOKOUT_DETECTOR') == 'hog', reason='pose weights not fetched (npm run models) or HOG forced')
def test_real_pose_model_loads_and_resets_tracker():
    pytest.importorskip('ultralytics')
    import cv2
    import numpy as np
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    engine = VisionEngine()
    engine.warm()
    assert engine.detector == 'pose'
    assert engine._detect(raw.tobytes()) == ([], 'active')
    engine.reset()
    assert engine._tracker_fresh
    assert engine._detect(raw.tobytes()) == ([], 'active')
    assert not engine._tracker_fresh
