"""Telegram alerts: mocked HTTP, never contacts Telegram."""
import asyncio
import json

import httpx
from server import providers

TOKEN = '123456:test-token'
JPEG = b'\xff\xd8blurred-frame\xff\xd9'
REAL_CLIENT = httpx.AsyncClient


def mock_telegram(monkeypatch, handler):
    monkeypatch.setattr(providers.httpx, 'AsyncClient', lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))


def configure(monkeypatch, chats='11'):
    monkeypatch.setenv('TELEGRAM_BOT_TOKEN', TOKEN)
    monkeypatch.setenv('TELEGRAM_CHAT_ID', chats)


def test_not_configured_sends_nothing(monkeypatch):
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
    monkeypatch.setenv('TELEGRAM_CHAT_ID', '1')
    mock_telegram(monkeypatch, lambda r: (_ for _ in ()).throw(AssertionError('no request expected')))
    assert asyncio.run(providers.telegram_send('x')) is None
    configure(monkeypatch, ' ')
    assert asyncio.run(providers.telegram_send('x')) is None


def test_sends_to_each_chat_and_counts_failures_without_raising(monkeypatch):
    configure(monkeypatch, '11, 22,33')
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append((request.url.path, body['chat_id'], body['text']))
        if body['chat_id'] == '22':
            return httpx.Response(403, json={'ok': False})
        if body['chat_id'] == '33':
            raise httpx.ConnectError('down: ' + str(request.url))
        return httpx.Response(200, json={'ok': True})

    mock_telegram(monkeypatch, handler)
    result = asyncio.run(providers.telegram_send('hello'))
    assert result == {'sent': 1, 'failed': 2}
    assert seen == [(f'/bot{TOKEN}/sendMessage', c, 'hello') for c in ('11', '22', '33')]


def test_photo_goes_as_one_sendphoto_with_the_caption(monkeypatch):
    configure(monkeypatch)
    seen = []

    def handler(request):
        seen.append((request.url.path.rsplit('/', 1)[1], JPEG in request.content, b'ollo alert' in request.content))
        return httpx.Response(200, json={'ok': True})

    mock_telegram(monkeypatch, handler)
    assert asyncio.run(providers.telegram_send('ollo alert', JPEG)) == {'sent': 1, 'failed': 0}
    assert seen == [('sendPhoto', True, True)]   # frame and caption in one upload, no duplicate text message


def test_photo_that_is_refused_or_errors_still_sends_the_text(monkeypatch):
    configure(monkeypatch)
    for photo in (lambda request: httpx.Response(400, json={'ok': False}),
                  lambda request: (_ for _ in ()).throw(httpx.ReadTimeout('slow upload: ' + str(request.url)))):
        methods = []

        def handler(request, photo=photo):
            methods.append(request.url.path.rsplit('/', 1)[1])
            return photo(request) if methods[-1] == 'sendPhoto' else httpx.Response(200, json={'ok': True})

        mock_telegram(monkeypatch, handler)
        assert asyncio.run(providers.telegram_send('ollo alert', JPEG)) == {'sent': 1, 'failed': 0}
        assert methods == ['sendPhoto', 'sendMessage']


def test_alert_text_names_room_event_and_step():
    incident = {'room': 'Toddler room', 'kind': 'fall'}
    assert providers.telegram_text(incident, 0) == 'ollo alert · Toddler room\nA possible fall was observed.\nPrimary caregiver escalation.'
    assert providers.telegram_text({**incident, 'kind': 'unknown'}, 1).endswith('Backup caregiver escalation.')
    assert providers.telegram_text(incident, 0, simulated=True).startswith('ollo alert (simulation, no call placed) · Toddler room')
