"""ESC-4: the keypad call works on a Twilio trial account. Mocked HTTP; never places calls."""
import asyncio
import hashlib
import os
import tempfile
import time
from urllib.parse import parse_qs

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='lookout-test-'))
import httpx
import pytest
from fastapi.testclient import TestClient
from twilio.request_validator import RequestValidator
from server.app import app, calls, store, watch_call
from server.providers import Calls

BASE = 'https://nestwatch.test'
SID = 'AC' + 'a' * 32
CALL = 'CA' + 'b' * 32
TRIAL_ENV = {'CALLS_ENABLED': 'true', 'CALL_ALLOWLIST': '+15551230001,+15551230002', 'CALL_PROVIDER': 'twilio',
             'PUBLIC_CALLBACK_BASE_URL': BASE, 'TWILIO_ACCOUNT_SID': SID, 'TWILIO_AUTH_TOKEN': 'test-secret',
             'TWILIO_FROM_NUMBER': '+15550000000', 'CARTESIA_API_KEY': 'test-key', 'CARTESIA_VOICE_ID': 'voice',
             'CARTESIA_MODEL_ID': 'sonic-3.6', 'CARTESIA_VERSION': '2026-08-14'}
sha = lambda token: hashlib.sha256(token.encode()).hexdigest()
REAL_CLIENT = httpx.AsyncClient


@pytest.fixture
def trial_env(monkeypatch):
    for key, value in TRIAL_ENV.items():
        monkeypatch.setenv(key, value)


def mock_twilio(monkeypatch, account_type, created, tunnel_up=True):
    """Cartesia returns audio; Twilio reports the account type and records each call it is asked to create.
    The tunnel (PUBLIC_CALLBACK_BASE_URL) answers /health when up, like ngrok forwarding to this server."""
    def handler(request):
        url = str(request.url)
        if url == BASE + '/health':
            return httpx.Response(200, json={'status': 'ok', 'purpose': 'process health only'}) if tunnel_up else httpx.Response(404, text='ERR_NGROK_3200 endpoint offline')
        if url.startswith('https://api.cartesia.ai/tts/bytes'):
            return httpx.Response(200, content=b'RIFF-test-audio')
        if url == f'https://api.twilio.com/2010-04-01/Accounts/{SID}.json':
            return httpx.Response(200, json={'sid': SID, 'type': account_type})
        if url == f'https://api.twilio.com/2010-04-01/Accounts/{SID}/Calls.json' and request.method == 'POST':
            created.append(parse_qs(request.content.decode()))
            return httpx.Response(201, json={'sid': CALL, 'status': 'queued'})
        return httpx.Response(404, json={'message': 'unexpected ' + url})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def test_trial_call_sends_only_to_from_url(trial_env, monkeypatch):
    created = []
    mock_twilio(monkeypatch, 'Trial', created)
    provider = Calls(None)
    async def place():
        result = await provider.place({'room': 'Toddler room', 'kind': 'fall'}, 0, True, caregiver='Maya Chen')
        return result, await provider.audio_for(created[0]['Url'][0].rsplit('/', 1)[1])
    result, audio = asyncio.run(place())
    form = created[0]
    assert set(form) == {'To', 'From', 'Url'}                    # no inline TwiML, no status callbacks
    assert form['To'] == ['+15551230001'] and form['From'] == ['+15550000000']
    url = form['Url'][0]
    assert url.startswith(BASE + '/webhooks/twilio/voice/')
    token = url.rsplit('/', 1)[1]
    assert len(token) >= 32 and audio == b'RIFF-test-audio'
    assert result['status'] == 'initiated' and result['provider'] == 'twilio' and result['call_sid'] == CALL
    assert result['call_token_sha256'] == sha(token) and token not in str(result)   # only the hash is stored

    paid = []
    mock_twilio(monkeypatch, 'Full', paid)
    asyncio.run(Calls(None).place({'room': 'Toddler room', 'kind': 'fall'}, 1, True, caregiver='James Wilson'))
    assert paid[0]['To'] == ['+15551230002']
    assert paid[0]['StatusCallback'] == [BASE + '/webhooks/twilio/status'] and 'Timeout' in paid[0]


def open_incident_with_call(client, token):
    client.get('/api/state'); client.post('/api/session/reset')
    incident = client.post('/api/demo/scenario', json={'scenario': 'boundary'}).json()['incidents'][0]
    job = dict(store.db.execute('SELECT * FROM jobs WHERE incident_id=? AND step=0', (incident['id'],)).fetchone())
    store.finish_job(job['id'], 'initiated', {'mode': 'real', 'provider': 'twilio', 'call_sid': CALL, 'call_token_sha256': sha(token)})
    calls.audio[token] = (time.time() + 900, b'RIFF-test-audio')
    return incident, job


def test_voice_instructions_and_unsigned_keypad_need_token_account_and_call(trial_env):
    token = 'tok-' + 'x' * 40
    with TestClient(app) as client:
        incident, _ = open_incident_with_call(client, token)
        ours = {'CallSid': CALL, 'AccountSid': SID}
        twiml = client.post(f'/webhooks/twilio/voice/{token}', data=ours)
        assert twiml.status_code == 200 and 'xml' in twiml.headers['content-type']
        assert f'{BASE}/call-media/{token}' in twiml.text and f'{BASE}/webhooks/twilio/digits/{token}' in twiml.text
        assert '<Gather' in twiml.text and 'numDigits="1"' in twiml.text
        assert client.post('/webhooks/twilio/voice/unknown-token-' + 'y' * 30, data=ours).status_code == 404

        digits = f'/webhooks/twilio/digits/{token}'
        assert client.post(digits, data={**ours, 'AccountSid': 'AC' + 'c' * 32, 'Digits': '1'}).status_code == 403
        assert client.post(digits, data={**ours, 'CallSid': 'CA' + 'd' * 32, 'Digits': '1'}).status_code == 403
        assert client.post(digits.replace(token, 'wrong-' + 'z' * 30), data={**ours, 'Digits': '1'}).status_code in (403, 404)
        bad = {**ours, 'Digits': '1'}
        assert client.post(digits, data=bad, headers={'X-Twilio-Signature': 'forged'}).status_code == 403
        assert store.incident(incident['id'])['status'] == 'open'

        signed = RequestValidator('test-secret').compute_signature(BASE + digits, bad)
        assert client.post(digits, data=bad, headers={'X-Twilio-Signature': signed}).status_code == 200
        handled = store.incident(incident['id'])
        assert handled['status'] == 'acknowledged' and handled['acknowledged_via'] == 'keypad'

        second, _ = open_incident_with_call(client, token + '2')
        reply = client.post(f'/webhooks/twilio/digits/{token}2', data={**ours, 'Digits': '2'})   # unsigned trial request
        assert reply.status_code == 200 and store.incident(second['id']).get('declined_at')


def test_polled_status_moves_forward_and_expedites_backup(trial_env, monkeypatch):
    token = 'poll-' + 'x' * 40
    with TestClient(app) as client:
        incident, job = open_incident_with_call(client, token)
        seen, hung_up = [], []
        sequence = iter(['ringing', 'in-progress', 'ringing', 'no-answer'])
        async def status(sid):
            seen.append(next(a for a in store.attempts() if a['id'] == job['id'])['status'])
            return next(sequence)
        async def cancel(sid):
            hung_up.append(sid)
        monkeypatch.setattr(calls, 'call_status', status)
        monkeypatch.setattr(calls, 'cancel', cancel)
        asyncio.run(watch_call(job['id'], CALL, every=0))
        attempt = next(a for a in store.attempts() if a['id'] == job['id'])
        assert seen == ['initiated', 'ringing', 'in-progress', 'in-progress']   # a late 'ringing' never moves it back
        assert attempt['status'] == 'no-answer' and not hung_up
        backup = dict(store.db.execute('SELECT * FROM jobs WHERE incident_id=? AND step=1', (incident['id'],)).fetchone())
        assert backup['status'] != 'queued' or backup['due'] <= time.time()     # the backup call is due now

        _, stuck = open_incident_with_call(client, token + '2')
        ringing = iter(['ringing', 'ringing', 'canceled'])
        async def still_ringing(sid):
            return next(ringing)
        monkeypatch.setattr(calls, 'call_status', still_ringing)
        asyncio.run(watch_call(stuck['id'], CALL, every=0, ring_limit=0))
        assert hung_up == [CALL]                                                # rang too long: hung up once


def test_unreachable_callback_blocks_arming_and_calls(trial_env, monkeypatch):
    created = []
    mock_twilio(monkeypatch, 'Trial', created, tunnel_up=False)
    calls.forget_callback_check()
    with TestClient(app) as client:
        client.get('/api/state'); client.post('/api/session/reset')
        refused = client.post('/api/session/arm-calls', json={'armed': True})
        assert refused.status_code == 409 and 'ngrok http 127.0.0.1:8000' in refused.json()['detail']
        assert client.get('/api/state').json()['session']['calls_armed'] is False
    result = asyncio.run(Calls(None).place({'room': 'Toddler room', 'kind': 'fall'}, 0, True))
    assert result['status'] == 'failed' and 'cannot reach' in result['message'] and created == []     # no phone rings into a dead tunnel

    mock_twilio(monkeypatch, 'Trial', created, tunnel_up=True)
    calls.forget_callback_check()
    with TestClient(app) as client:
        client.get('/api/state')
        assert client.post('/api/session/arm-calls', json={'armed': True}).status_code == 200
        client.post('/api/session/reset')
    assert asyncio.run(Calls(None).place({'room': 'Toddler room', 'kind': 'fall'}, 0, True))['status'] == 'initiated'
