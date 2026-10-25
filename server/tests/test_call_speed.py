"""ESC-5: the keypad call never waits for Cartesia speech. Mocked HTTP; never places calls."""
import asyncio
import os
import tempfile
import time

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='lookout-test-'))
import httpx
import pytest
from fastapi.testclient import TestClient
from server.app import app, calls, store
from server.providers import Calls
from server.store import KINDS

BASE = 'https://nestwatch.test'
SID = 'AC' + 'a' * 32
CALL = 'CA' + 'b' * 32
ENV = {'CALLS_ENABLED': 'true', 'CALL_ALLOWLIST': '+15551230001', 'CALL_PROVIDER': 'twilio', 'PUBLIC_CALLBACK_BASE_URL': BASE,
       'TWILIO_ACCOUNT_SID': SID, 'TWILIO_AUTH_TOKEN': 'test-secret', 'TWILIO_FROM_NUMBER': '+15550000000',
       'CARTESIA_API_KEY': 'test-key', 'CARTESIA_VOICE_ID': 'voice', 'CARTESIA_MODEL_ID': 'sonic-3.6', 'CARTESIA_VERSION': '2026-08-14'}
REAL_CLIENT = httpx.AsyncClient


@pytest.fixture
def env(monkeypatch):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)


def mock(monkeypatch, speech):
    """Twilio creates calls and reports a trial account; `speech(request)` answers Cartesia. Returns the request log."""
    log = []
    async def handler(request):
        url = str(request.url)
        if url.startswith('https://api.cartesia.ai/tts/bytes'):
            log.append('speech requested')
            response = await speech(request)
            log.append('speech done')
            return response
        if url == BASE + '/health':
            return httpx.Response(200, json={'status': 'ok', 'purpose': 'process health only'})
        if url.endswith(f'/Accounts/{SID}.json'):
            return httpx.Response(200, json={'type': 'Trial'})
        if url.endswith('/Calls.json'):
            log.append('call created')
            return httpx.Response(201, json={'sid': CALL})
        return httpx.Response(404)
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    return log


def token_of(provider):
    return next(iter(provider.pending))


def test_call_is_created_before_speech_is_ready(env, monkeypatch):
    created = asyncio.Event()
    async def slow_speech(request):
        await asyncio.wait_for(created.wait(), 2)       # only finishes once the call exists: waiting first would time out
        return httpx.Response(200, content=b'RIFF-audio')
    log = mock(monkeypatch, slow_speech)
    async def run():
        provider = Calls(None)
        placing = asyncio.create_task(provider.place({'room': 'Toddler room', 'kind': 'fall'}, 0, True))
        while 'call created' not in log and not placing.done():
            await asyncio.sleep(0.01)
        created.set()
        result = await placing
        return result, await provider.audio_for(token_of(provider))
    result, audio = asyncio.run(run())
    assert result['status'] == 'initiated' and result['call_sid'] == CALL
    assert log.index('call created') < log.index('speech done')
    assert audio == b'RIFF-audio'


def test_answered_call_waits_for_speech_or_falls_back_to_say(env, monkeypatch):
    async def late_speech(request):
        await asyncio.sleep(0.2)
        return httpx.Response(200, content=b'RIFF-audio')
    mock(monkeypatch, late_speech)
    async def answered(kind):
        provider = Calls(None)
        result = await provider.place({'room': 'Toddler room', 'kind': kind}, 0, True)
        return result, await provider.twiml(token_of(provider)), token_of(provider), provider
    result, twiml, token, provider = asyncio.run(answered('fall'))
    assert result['status'] == 'initiated'
    assert f'<Play>{BASE}/call-media/{token}</Play>' in twiml and f'{BASE}/webhooks/twilio/digits/{token}' in twiml
    assert asyncio.run(provider.twiml('unknown-token')) is None

    async def broken_speech(request):
        return httpx.Response(500, json={'error': 'overloaded'})
    mock(monkeypatch, broken_speech)
    result, twiml, token, _ = asyncio.run(answered('distress'))
    assert result['status'] == 'initiated'                               # the call goes out without Cartesia
    assert '<Say>' in twiml and 'Press 1 to acknowledge' in twiml and '<Play>' not in twiml
    assert '<Gather' in twiml and f'{BASE}/webhooks/twilio/digits/{token}' in twiml


def test_arming_prepares_speech_for_every_kind_once(env, monkeypatch):
    async def speech(request):
        return httpx.Response(200, content=b'RIFF-' + request.content[-12:])
    log = mock(monkeypatch, speech)
    calls.speech_cache.clear()
    with TestClient(app) as client:
        client.get('/api/state'); client.post('/api/session/reset')
        room = store.get('settings')['room_label']
        assert client.post('/api/session/arm-calls', json={'armed': True}).status_code == 200
        deadline = time.time() + 5
        while log.count('speech done') < len(KINDS) and time.time() < deadline:
            time.sleep(0.05)
        assert log.count('speech requested') == len(KINDS)
        assert all(calls.message({'room': room, 'kind': kind}) in calls.speech_cache for kind in KINDS)
        assert calls._trial is True
        client.post('/api/session/arm-calls', json={'armed': False})
        assert client.post('/api/session/arm-calls', json={'armed': True}).status_code == 200
        time.sleep(0.3)
        assert log.count('speech requested') == len(KINDS)                 # already prepared: no second request
        client.post('/api/session/reset')
