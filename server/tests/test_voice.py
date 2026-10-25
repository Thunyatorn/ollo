"""ESC-3 / UI-3: Cartesia voice-agent calls and spoken acknowledgment. Mocked HTTP; never places calls."""
import asyncio
import hashlib
import json
import os
import tempfile

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='lookout-test-'))
import httpx
import pytest
from fastapi.testclient import TestClient
from server.app import app, store
from server.providers import Calls, ready

AGENT_ENV = {'CALLS_ENABLED': 'true', 'CALL_ALLOWLIST': '+15551230001,+15551230002', 'CALL_PROVIDER': 'cartesia_agent',
             'CARTESIA_API_KEY': 'test-key', 'CARTESIA_AGENT_ID': 'agent_test', 'CARTESIA_FROM_NUMBER_ID': 'ap_test',
             'VOICE_WEBHOOK_SECRET': 'test-secret', 'PUBLIC_CALLBACK_BASE_URL': 'https://nestwatch.test'}
sha = lambda token: hashlib.sha256(token.encode()).hexdigest()


@pytest.fixture
def agent_env(monkeypatch):
    for key, value in AGENT_ENV.items():
        monkeypatch.setenv(key, value)
    for key in ('TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_FROM_NUMBER'):
        monkeypatch.delenv(key, raising=False)


def mock_http(monkeypatch, handler):
    real = httpx.AsyncClient
    def with_tunnel(request):              # PUBLIC_CALLBACK_BASE_URL reaches this server (ESC-1)
        if str(request.url).endswith('/health'):
            return httpx.Response(200, json={'status': 'ok', 'purpose': 'process health only'})
        return handler(request)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(with_tunnel), **kw))


def test_cartesia_agent_places_call_with_hashed_token(agent_env, monkeypatch):
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, json={'calls': [{'number': '+15551230001', 'agent_call_id': 'ac_1'}]})
    mock_http(monkeypatch, handler)
    assert ready()
    result = asyncio.run(Calls(None).place({'room': 'Toddler room', 'kind': 'fall', 'title': 'Possible fall'}, 0, True, caregiver='Maya Chen'))
    request = sent[0]
    body = json.loads(request.content)
    assert str(request.url) == 'https://api.cartesia.ai/agents/calls'
    assert request.headers['X-API-Key'] == 'test-key' and request.headers['Cartesia-Version']
    assert body['agent_id'] == 'agent_test' and body['from_number_id'] == 'ap_test'
    call = body['outbound_calls'][0]
    assert call['to_number'] == '+15551230001'
    variables = call['dynamic_variables']
    assert variables['room'] == 'Toddler room' and variables['alert'] == 'Possible fall' and variables['caregiver'] == 'Maya Chen'
    assert result['status'] == 'initiated' and result['provider'] == 'cartesia_agent' and result['agent_call_id'] == 'ac_1'
    assert result['ack_token_sha256'] == sha(variables['ack_token'])
    assert variables['ack_token'] not in json.dumps(result)  # Only the hash is stored.


def placed(incident_id, step, token):
    job = dict(store.db.execute('SELECT * FROM jobs WHERE incident_id=? AND step=?', (incident_id, step)).fetchone())
    store.finish_job(job['id'], 'initiated', {'mode': 'real', 'provider': 'cartesia_agent', 'agent_call_id': f'ac_{step}', 'ack_token_sha256': sha(token)})


def test_voice_webhook_acknowledges_once_and_checks_secret(agent_env):
    with TestClient(app) as client:
        client.get('/api/state')
        client.post('/api/session/reset')
        incident = client.post('/api/demo/scenario', json={'scenario': 'boundary'}).json()['incidents'][0]
        placed(incident['id'], 0, 'token-primary-1')
        ack = {'token': 'token-primary-1', 'decision': 'acknowledge'}
        assert client.post('/webhooks/voice/ack', json=ack).status_code == 403
        assert client.post('/webhooks/voice/ack', json=ack, headers={'Authorization': 'Bearer wrong'}).status_code == 403
        auth = {'Authorization': 'Bearer test-secret'}
        assert client.post('/webhooks/voice/ack', json={**ack, 'token': 'token-unknown'}, headers=auth).status_code == 409
        reply = client.post('/webhooks/voice/ack', json=ack, headers=auth)
        assert reply.status_code == 200 and 'Acknowledged' in reply.text
        current = store.incident(incident['id'])
        primary = store.get('settings').get('primary_name', 'Maya Chen')
        assert current['status'] == 'acknowledged' and current['assigned_responder'] == primary and current['acknowledged_via'] == 'voice'
        assert client.post('/webhooks/voice/ack', json=ack, headers=auth).status_code == 409  # Single use.


def test_voice_decline_and_already_handled_replies(agent_env):
    auth = {'Authorization': 'Bearer test-secret'}
    with TestClient(app) as client:
        client.get('/api/state')
        client.post('/api/session/reset')
        incident = client.post('/api/demo/scenario', json={'scenario': 'boundary'}).json()['incidents'][0]
        placed(incident['id'], 0, 'token-primary-2')
        placed(incident['id'], 1, 'token-backup-2')
        declined = client.post('/webhooks/voice/ack', json={'token': 'token-primary-2', 'decision': 'decline'}, headers=auth)
        assert declined.status_code == 200 and 'backup' in declined.text.lower()
        assert store.incident(incident['id']).get('declined_at')
        client.post(f"/api/incidents/{incident['id']}/acknowledge", json={'actor': 'Dana'})
        late = client.post('/webhooks/voice/ack', json={'token': 'token-backup-2', 'decision': 'acknowledge'}, headers=auth)
        assert late.status_code == 200 and 'already handled by Dana' in late.text
        current = store.incident(incident['id'])
        assert current['assigned_responder'] == 'Dana' and current['acknowledged_via'] == 'dashboard'


def test_failed_agent_call_falls_back_to_keypad(agent_env, monkeypatch):
    for key, value in {'TWILIO_ACCOUNT_SID': 'AC-test', 'TWILIO_AUTH_TOKEN': 'test', 'TWILIO_FROM_NUMBER': '+15550000000',
                       'CARTESIA_VOICE_ID': 'voice', 'CARTESIA_MODEL_ID': 'sonic', 'CARTESIA_VERSION': '2026-08-14'}.items():
        monkeypatch.setenv(key, value)
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={'calls': [{'number': '+15551230001', 'error': 'number not verified'}]}))
    calls = Calls(None)
    async def keypad(incident, step, destination, still_authorized=None):
        return {'status': 'initiated', 'mode': 'real', 'provider': 'twilio', 'call_sid': 'CA-fallback'}
    monkeypatch.setattr(calls, '_place_twilio', keypad)
    result = asyncio.run(calls.place({'room': 'Toddler room', 'kind': 'boundary', 'title': 'Restricted-area activity'}, 0, True, caregiver='Maya Chen'))
    assert result['provider'] == 'twilio' and result['fallback_from'] == 'cartesia_agent' and 'not verified' in result['fallback_reason']
