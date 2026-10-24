"""Geometry, lifecycle and schema tests; not detection/medical validation."""
import asyncio
import base64

import pytest
from pydantic import ValidationError
from server.vision import ReviewResult, VisionEngine, ZoneTracker, jpeg_dimensions, point_in_polygon, valid_polygon


SQUARE = [(0.5, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.9)]


def test_polygon_and_validation():
    assert point_in_polygon((0.7, 0.5), SQUARE)
    assert point_in_polygon((0.5, 0.5), SQUARE)
    assert not point_in_polygon((0.2, 0.5), SQUARE)
    assert valid_polygon(SQUARE) == SQUARE
    assert valid_polygon([(0, 0), (1, 1), (0.5, 0.5)]) == []
    assert valid_polygon([(0, 0), (float('nan'), 0), (1, 1)]) == []
    assert valid_polygon([(0, 0), (2, 0), (1, 1)]) == []


def test_hysteresis_presence_crossing_and_loss():
    tracker = ZoneTracker()
    assert [tracker.update(True) for _ in range(3)] == [None, None, 'present']
    assert tracker.update(False) is None
    assert tracker.update(True) is None
    assert [tracker.update(False) for _ in range(3)] == [None, None, None]
    assert tracker.update(True) is None
    assert tracker.update(None) is None
    assert [tracker.update(True) for _ in range(3)] == [None, None, 'entered']


def test_schema_abstention_and_required_evidence():
    result = dict(assessment='insufficient_view', observations=[], visibility='poor', alternative_explanations=[], limitations=['Airway status cannot be determined.'])
    assert ReviewResult.model_validate(result).assessment == 'insufficient_view'
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({**result, 'assessment': 'possible_distress'})
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({**result, 'assessment': 'choking_confirmed'})
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({**result, 'call_number': '+15555555555'})


def test_jpeg_bounds_and_blank_detector():
    import cv2
    import numpy as np
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    jpeg = raw.tobytes()
    assert jpeg_dimensions(jpeg) == (640, 360)
    with pytest.raises(ValueError):
        jpeg_dimensions(b'not a jpeg')
    with pytest.raises(ValueError):
        jpeg_dimensions(b'\xff\xd8' + b'x' * 1_500_000)
    boxes, status = VisionEngine()._detect(jpeg)
    assert boxes == []
    assert status == 'active'


def test_frames_epoch_order_and_boundary():
    import cv2
    import numpy as np
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    encoded = base64.b64encode(raw).decode()
    engine = VisionEngine({'zone': {'vertices': SQUARE}})
    # Inject observed bounding boxes solely for deterministic rule verification.
    position = {'x': .05}
    engine._detect = lambda _: ([{'x': position['x'], 'y': .2, 'width': .1, 'height': .3}], 'active')
    def frame(seq, epoch=1):
        return dict(session_id='s1', epoch=epoch, frame_seq=seq, media_time_ms=seq * 250, image=encoded)
    async def scenario():
        for i in range(3):
            assert not (await engine.process_frame(frame(i)))['observations']
        # Advance gradually to preserve the single-person association.
        position['x'] = .25
        await engine.process_frame(frame(3))
        position['x'] = .5
        for i in range(4, 6):
            assert not (await engine.process_frame(frame(i)))['observations']
        result = await engine.process_frame(frame(6))
        assert result['observations'][0]['kind'] == 'boundary'
        assert result['observations'][0]['origin'] == 'local_rule'
        assert (await engine.process_frame(frame(5)))['rejected'] == 'out_of_order'
        assert (await engine.process_frame(frame(7, epoch=0)))['rejected'] == 'wrong_epoch'
        engine.reset('s1', 2)
        assert (await engine.process_frame(frame(1, epoch=1)))['rejected'] == 'wrong_epoch'
        assert not (await engine.process_frame(frame(0, epoch=2)))['observations']
    asyncio.run(scenario())


@pytest.mark.parametrize('assessment,reference,expected', [('possible_distress', 0, 1), ('insufficient_view', 0, 0), ('possible_distress', 999, 0)])
def test_provider_schema_and_evidence_references(monkeypatch, assessment, reference, expected):
    import httpx
    engine = VisionEngine()
    engine.session_id, engine.epoch, engine.last_media_time = 's1', 1, 1250
    for i in range(6):
        engine.frames.append({'frame_seq': i, 'media_time_ms': i * 250, 'jpeg': b'staged-test-placeholder'})
    payload = dict(assessment=assessment, observations=[{'frame_seq': reference, 'description': 'Hands near neck in staged footage'}], visibility='partial', alternative_explanations=['Could be play'], limitations=['Airway status cannot be determined from video.'])
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'content': [{'type': 'tool_use', 'name': 'report_observations', 'input': payload}]}))
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(transport=transport, **kw))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'mock-not-a-key')
    monkeypatch.setenv('VISION_MODEL', 'mock-model')
    result = asyncio.run(engine.review_window())
    assert len(result['observations']) == expected
    if reference == 999:
        assert result['review_status'] == 'unavailable'
    if expected:
        assert result['observations'][0]['origin'] == 'model'
        assert result['observations'][0]['evidence_frame_seq'] == 5


def test_late_cloud_result_discarded_after_reset(monkeypatch):
    import httpx
    engine = VisionEngine()
    engine.session_id, engine.epoch, engine.last_media_time = 's1', 1, 1250
    for i in range(6):
        engine.frames.append({'frame_seq': i, 'media_time_ms': i * 250, 'jpeg': b'staged-test-placeholder'})
    async def handler(request):
        engine.reset('s1', 2)
        return httpx.Response(200, json={'content': [{'type': 'tool_use', 'name': 'report_observations', 'input': {'assessment': 'possible_distress', 'observations': [{'frame_seq': 0, 'description': 'Staged gesture'}], 'visibility': 'partial', 'alternative_explanations': [], 'limitations': ['Cannot assess airway']}}]})
    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'mock-not-a-key')
    monkeypatch.setenv('VISION_MODEL', 'mock-model')
    result = asyncio.run(engine.review_window())
    assert result['observations'] == []
    assert result['review_status'] == 'expired'
    assert engine.last_review is None
