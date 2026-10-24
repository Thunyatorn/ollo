"""Claude second opinion: trigger, privacy crop, schema, cost, failure isolation. Fake client, no network."""
import asyncio
import base64
import json
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError
from server.review import ReviewResult, cost_usd, crop_frames
from server.tests.test_events import skeleton
from server.vision import VisionEngine

OPINION = {'assessment': 'concern_visible', 'observations': [{'frame_seq': 0, 'description': 'Both hands held at the neck.'}],
           'visibility': 'partial', 'alternative_explanations': ['Could be play'], 'limitations': ['Airway status cannot be determined from video.']}


class FakeMessages:
    def __init__(self, log, stop='end_turn', payload=None, on_call=None):
        self.log, self.stop, self.payload, self.on_call = log, stop, payload, on_call

    async def create(self, **kwargs):
        self.log.append(kwargs)
        if self.on_call:
            self.on_call()
        payload = self.payload or {**OPINION, 'observations': [{'frame_seq': self._first_seq(kwargs), 'description': 'Both hands held at the neck.'}]}
        return SimpleNamespace(stop_reason=self.stop, model=kwargs['model'], usage=SimpleNamespace(input_tokens=1500, output_tokens=200),
                               content=[SimpleNamespace(type='text', text=json.dumps(payload))])

    @staticmethod
    def _first_seq(kwargs):
        text = next(b['text'] for b in kwargs['messages'][0]['content'] if b['type'] == 'text' and b['text'].startswith('frame_seq='))
        return int(text.split('=')[1])


def fake_client(log, **kwargs):
    messages = FakeMessages(log, **kwargs)
    return SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))


def textured_jpeg():
    """Checkerboard so blur is measurable."""
    import cv2
    image = (np.indices((360, 640)).sum(axis=0) % 2 * 255).astype(np.uint8)
    _, raw = cv2.imencode('.jpg', cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
    return raw.tobytes()


def run_engine(engine, people_at, frames=24, fps=4):
    import cv2
    _, raw = cv2.imencode('.jpg', np.full((360, 640, 3), 128, dtype=np.uint8))
    image = base64.b64encode(raw).decode()
    async def scenario():
        found = []
        for seq in range(frames):
            engine._detect = lambda _, s=seq: (people_at(s / fps), 'active')
            found += (await engine.process_frame(dict(session_id='s1', epoch=1, frame_seq=seq, media_time_ms=seq * 1000 / fps, image=image)))['observations']
            if engine._task is not None:
                await asyncio.wait({engine._task})  # Deterministic: a started review finishes before the next frame.
        return found
    return asyncio.run(scenario())


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-not-a-key')
    monkeypatch.setenv('VISION_MODEL', 'claude-haiku-5-5')


def test_schema_abstention_and_required_evidence():
    abstain = dict(OPINION, assessment='insufficient_view', observations=[])
    assert ReviewResult.model_validate(abstain).assessment == 'insufficient_view'
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({**abstain, 'assessment': 'concern_visible'})
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({**OPINION, 'assessment': 'choking_confirmed'})
    with pytest.raises(ValidationError):
        ReviewResult.model_validate({**OPINION, 'call_number': '+15555555555'})


def test_crop_blurs_heads_and_keeps_only_the_flagged_person():
    jpeg = textured_jpeg()
    subject, other = {**skeleton(x0=0.9, top=0.15), 'track_id': 1}, {**skeleton(x0=0.3, top=0.15), 'track_id': 2}
    frames = [{'frame_seq': i, 'media_time_ms': i * 250, 'jpeg': jpeg, 'people': {1: subject, 2: other}} for i in range(10)]
    crops = crop_frames(frames, 1)
    assert [seq for seq, _ in crops] == [0, 3, 6, 9]
    import cv2
    crop = cv2.imdecode(np.frombuffer(crops[0][1], dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert max(crop.shape) <= 512 and crop.shape[1] < 640 * 0.5  # Only the subject's region, not the other person.
    # Detail map in 8×8 blocks: the blurred head is a near-flat block in the upper part of the crop,
    # while the untouched checkerboard elsewhere keeps full detail.
    detail = np.abs(np.diff(crop.astype(float), axis=1))
    h, w = (detail.shape[0] // 8) * 8, (detail.shape[1] // 8) * 8
    blocks = detail[:h, :w].reshape(h // 8, 8, w // 8, 8).mean(axis=(1, 3))
    assert blocks[: blocks.shape[0] * 2 // 5].min() < 0.2 * np.median(blocks[blocks.shape[0] // 2:])
    assert crop_frames(frames, 99) == []


def test_review_runs_only_after_a_local_alert(configured):
    log = []
    engine = VisionEngine({'cloud_review_enabled': True})
    engine._client = fake_client(log)
    calm = run_engine(engine, lambda t: [skeleton()], frames=40)
    assert log == [] and not calm and engine.cloud['requests'] == 0  # Nothing happening costs nothing.
    engine.reset()
    engine._client = fake_client(log)
    found = run_engine(engine, lambda t: [skeleton(wrists='throat')], frames=24)
    kinds = [o['kind'] for o in found]
    assert kinds.index('distress') < kinds.index('review') and len(log) == 1
    request = log[0]
    assert request['model'] == 'claude-haiku-5-5' and 'fallbacks' not in request
    assert request['output_config']['format']['type'] == 'json_schema' and 'tool_choice' not in request
    assert sum(1 for b in request['messages'][0]['content'] if b['type'] == 'image') <= 4
    review = next(o for o in found if o['kind'] == 'review')
    assert review['target_kind'] == 'distress' and review['review']['faces_blurred']
    assert engine.cloud['cost_usd'] == pytest.approx(cost_usd('claude-haiku-5-5', 1500, 200))


def test_fallbacks_for_models_with_safety_declines(configured, monkeypatch):
    monkeypatch.setenv('VISION_MODEL', 'claude-opus-5-5')
    log = []
    engine = VisionEngine({'cloud_review_enabled': True})
    engine._client = fake_client(log)
    run_engine(engine, lambda t: [skeleton(wrists='throat')], frames=24)
    assert log[0]['fallbacks'] == 'default' and log[0]['betas'] == ['server-side-fallback-2026-07-01']


def test_decline_or_late_result_never_touches_the_alert(configured):
    log = []
    engine = VisionEngine({'cloud_review_enabled': True})
    engine._client = fake_client(log, stop='refusal')
    found = run_engine(engine, lambda t: [skeleton(wrists='throat')], frames=24)
    assert 'distress' in [o['kind'] for o in found] and 'review' not in [o['kind'] for o in found]
    assert engine.review_status == 'unavailable'
    engine = VisionEngine({'cloud_review_enabled': True})
    engine._client = fake_client(log, on_call=lambda: engine.reset())  # Session reset while the request is in flight.
    found = run_engine(engine, lambda t: [skeleton(wrists='throat')], frames=24)
    assert 'review' not in [o['kind'] for o in found] and engine.last_review is None


def test_cost_table():
    assert cost_usd('claude-haiku-5-5', 1_000_000, 1_000_000) == pytest.approx(0.60)
    assert cost_usd('claude-opus-5-5', 1500, 200) == pytest.approx(0.01)
    assert cost_usd('unknown-model', 1, 1) is None


def test_callback_attaches_opinion_without_changing_incident_status(configured, tmp_path):
    from server.store import Store
    store = Store(tmp_path / 'test.sqlite3')
    incident = store.observe('distress', ['Both hands at throat'], 'local_rule', 'critical')
    log = []
    engine = VisionEngine({'cloud_review_enabled': True})
    engine._client = fake_client(log)
    engine.on_review = store.annotate
    found = run_engine(engine, lambda t: [skeleton(wrists='throat')], frames=24)
    assert 'review' not in [o['kind'] for o in found]  # Delivered by callback, not by a later frame.
    stored = store.incident(incident['id'])
    assert stored['second_opinion']['assessment'] == 'concern_visible'
    assert stored['status'] == 'open' and stored['priority'] == 'critical'
    assert store.events()[0]['type'] == 'second_opinion'
