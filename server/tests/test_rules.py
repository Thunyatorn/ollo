"""AI-6 plain-language rules: landmarks, Claude drafts (fake client), schedules, enforcement."""
import asyncio
import base64
import json
import os
import tempfile
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='lookout-test-'))
import numpy as np
import pytest
from fastapi.testclient import TestClient
import server.app as api
from server.rules import schedule_active
from server.vision import VisionEngine

GATE = [[0.6, 0.4], [0.9, 0.4], [0.9, 0.9], [0.6, 0.9]]


class FakeClaude:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.messages = self.beta = self
        self.beta.messages = self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.reply(kwargs) if callable(self.reply) else self.reply
        return SimpleNamespace(stop_reason='end_turn', model=kwargs['model'], usage=SimpleNamespace(input_tokens=400, output_tokens=60),
                               content=[SimpleNamespace(type='text', text=json.dumps(reply))])


def proposal(landmark_id, **overrides):
    return {'action': 'propose', 'landmark_id': landmark_id, 'schedule': 'window', 'start': '12:30', 'end': '14:30',
            'severity': 'high', 'summary': 'Keep children away from the kitchen gate during nap time.', 'question': None, **overrides}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test-not-a-key')
    monkeypatch.delenv('CLAUDE_MODEL', raising=False)
    with TestClient(api.app) as c:
        c.get('/api/state')
        settings = api.store.get('settings')
        settings['landmarks'], settings['rules'] = [], []
        api.store.put('settings', settings)
        yield c


def add_gate(client):
    return client.post('/api/landmarks', json={'name': 'Kitchen gate', 'vertices': GATE}).json()['settings']['landmarks'][-1]


def test_landmark_validation_and_cascade_delete(client, monkeypatch):
    gate = add_gate(client)
    assert gate['name'] == 'Kitchen gate' and gate['vertices'] == GATE
    for bad in ({'name': 'kitchen GATE', 'vertices': GATE}, {'name': 'Stairs', 'vertices': GATE[:2]},
                {'name': 'Stairs', 'vertices': [[0.1, 0.1], [1.4, 0.1], [0.5, 0.5]]}, {'name': '', 'vertices': GATE}, {'name': 'x' * 41, 'vertices': GATE}):
        assert client.post('/api/landmarks', json=bad).status_code == 422
    monkeypatch.setattr(api, 'claude_client', lambda: FakeClaude(proposal(gate['id'])))
    rule = client.post('/api/rules/draft', json={'text': 'Keep kids away from the kitchen gate during nap time'}).json()['rule']
    settings = client.delete(f"/api/landmarks/{gate['id']}").json()['settings']
    assert settings['landmarks'] == [] and all(r['id'] != rule['id'] for r in settings['rules'])


def test_draft_proposal_is_saved_as_draft(client, monkeypatch):
    gate = add_gate(client)
    fake = FakeClaude(proposal(gate['id']))
    monkeypatch.setattr(api, 'claude_client', lambda: fake)
    body = client.post('/api/rules/draft', json={'text': 'Keep kids away from the kitchen gate during nap time'}).json()
    rule = body['rule']
    assert rule['status'] == 'draft' and rule['landmark_id'] == gate['id'] and rule['schedule'] == {'type': 'window', 'start': '12:30', 'end': '14:30'}
    assert rule['severity'] == 'high' and rule['source_text'].startswith('Keep kids')
    request = fake.calls[0]
    assert request['model'] == 'claude-opus-5-5' and request['fallbacks'] == 'default'
    assert request['output_config']['format']['type'] == 'json_schema' and request['output_config']['effort'] == 'low'
    prompt = json.dumps(request['messages'])
    assert 'Kitchen gate' in prompt and gate['id'] in prompt and 'nap time' in prompt
    confirmed = client.post(f"/api/rules/{rule['id']}/confirm").json()['settings']['rules']
    assert [r['status'] for r in confirmed if r['id'] == rule['id']] == ['active']
    assert all(r['id'] != rule['id'] for r in client.delete(f"/api/rules/{rule['id']}").json()['settings']['rules'])


def test_unknown_landmark_or_bad_time_becomes_a_question(client, monkeypatch):
    gate = add_gate(client)
    for reply in (proposal('lm-does-not-exist'), proposal(gate['id'], start='25:99'),
                  {'action': 'clarify', 'landmark_id': None, 'schedule': None, 'start': None, 'end': None, 'severity': None, 'summary': None, 'question': 'Which gate do you mean?'}):
        monkeypatch.setattr(api, 'claude_client', lambda r=reply: FakeClaude(r))
        body = client.post('/api/rules/draft', json={'text': 'Keep kids off the gate'}).json()
        assert body.get('question') and 'rule' not in body
        assert api.store.get('settings')['rules'] == []
    assert client.post('/api/rules/draft', json={'text': 'x' * 301}).status_code == 422


def test_draft_without_claude_creates_nothing(client, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY')
    add_gate(client)
    assert client.post('/api/rules/draft', json={'text': 'Keep kids away from the kitchen gate'}).status_code == 503
    assert api.store.get('settings')['rules'] == []


def test_schedule_windows_wrap_and_nap():
    at = lambda h, m=0: datetime(2026, 10, 24, h, m)
    lunch = {'type': 'window', 'start': '12:30', 'end': '14:30'}
    assert schedule_active(lunch, at(13), False) and not schedule_active(lunch, at(15), False) and not schedule_active(lunch, at(12, 29), False)
    night = {'type': 'window', 'start': '22:00', 'end': '06:00'}
    assert schedule_active(night, at(23), False) and schedule_active(night, at(5), False) and not schedule_active(night, at(12), False)
    assert schedule_active({'type': 'nap'}, at(9), True) and not schedule_active({'type': 'nap'}, at(9), False)
    assert schedule_active({'type': 'always'}, at(3), False)


def test_engine_enforces_only_confirmed_rules_in_schedule():
    import cv2
    _, raw = cv2.imencode('.jpg', np.zeros((360, 640, 3), dtype=np.uint8))
    image = base64.b64encode(raw).decode()
    def person(t):
        u = min(0.2 + 0.25 * t, 0.75)  # Walks into the gate and stays.
        keypoints = [[0.0, 0.0, 0.0]] * 17
        keypoints[15] = keypoints[16] = [u, 0.8, 0.9]
        return {'x': u - 0.03, 'y': 0.4, 'width': 0.06, 'height': 0.42, 'confidence': 0.9, 'track_id': 2, 'keypoints': keypoints}
    def run(status, hour):
        rule = {'id': 'r1', 'landmark_id': 'lm1', 'schedule': {'type': 'window', 'start': '12:30', 'end': '14:30'}, 'severity': 'critical', 'status': status}
        engine = VisionEngine({'zone': {'enabled': False, 'vertices': GATE}, 'landmarks': [{'id': 'lm1', 'name': 'Kitchen gate', 'vertices': GATE}], 'rules': [rule]})
        engine.clock = lambda: datetime(2026, 10, 24, hour, 0)
        async def scenario():
            found = []
            for seq in range(36):
                t = seq / 12
                engine._detect = lambda _, t=t: ([person(t)], 'active')
                found += (await engine.process_frame(dict(session_id='s1', epoch=1, frame_seq=seq, media_time_ms=t * 1000, image=image)))['observations']
            return found
        return asyncio.run(scenario())
    enforced = run('active', 13)
    assert [o['kind'] for o in enforced] == ['boundary'] and 'Kitchen gate' in enforced[0]['observations'][0]
    assert enforced[0]['priority'] == 'critical'
    assert run('active', 15) == []   # Outside its window.
    assert run('draft', 13) == []    # Never enforced before confirmation.
