"""SRC-4 server-side camera capture. Fake cameras stand in for cv2.VideoCapture; tests never open a real camera."""
import asyncio
import base64
import json
import os
import tempfile
import threading
import time

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='lookout-test-'))
os.environ.setdefault('CALLS_ENABLED', 'false')

import numpy as np
import pytest

import server.capture as capture_module
from server.capture import CameraCapture, mask, parse_camera
from server.vision import jpeg_dimensions


class FakeCamera:
    """Delivers generated 1280×720 frames at `fps`, blocking in read() like a webcam.

    `stalled` blocks read() (a stream that stops sending but stays connected); `ends_after`
    makes read() fail after that many frames (a dropped stream); `opened=False` fails to open.
    """

    def __init__(self, fps=30, ends_after=None, opened=True):
        self.fps, self.ends_after, self.opened = fps, ends_after, opened
        self.stalled = self.finished = self.released = False
        self.count = 0

    def isOpened(self):
        return self.opened

    def set(self, *args):
        return True

    def read(self):
        time.sleep(1 / self.fps)
        while self.stalled and not self.finished:
            time.sleep(0.01)
        if self.finished or not self.opened or (self.ends_after is not None and self.count >= self.ends_after):
            return False, None
        self.count += 1
        image = np.full((720, 1280, 3), 30, dtype=np.uint8)
        image[300:420, (self.count * 7) % 1100:(self.count * 7) % 1100 + 120] = 200
        return True, image

    def release(self):
        self.released = True


def wait_until(predicate, timeout):
    """Poll from synchronous test code; returns seconds taken, or None on timeout."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return time.monotonic() - start
        time.sleep(0.02)
    return None


def test_camera_spec_accepts_index_and_stream_urls_only():
    assert parse_camera('0') == 0 and parse_camera(' 3 ') == 3 and parse_camera(9) == 9
    for url in ('rtsp://nest:secret@10.0.0.5:554/stream1', 'rtsps://cam.local/live', 'http://127.0.0.1:8080/video', 'https://cam.example/stream.mjpg'):
        assert parse_camera(url) == url
    for bad in ('', '10', '-1', '1.5', '/dev/video0', 'file:///etc/passwd', 'concat:a.mp4|b.mp4', 'ftp://cam/x', 'rtsp://', 'rtsp:///path',
                'rtsp://cam/a b', 'rtsp://cam/\x00', 'rtsp://cam/' + 'x' * 500, True, None, 1.5, -1, 10, ['rtsp://cam']):
        with pytest.raises(ValueError):
            parse_camera(bad)
    assert mask('rtsp://nest:secret@10.0.0.5:554/stream1') == 'rtsp://nest:***@10.0.0.5:554/stream1'
    assert mask('http://127.0.0.1:8080/video') == 'http://127.0.0.1:8080/video'
    assert mask(0) == 'Webcam 0'


def test_capture_samples_newest_frames_at_12_fps():
    camera = FakeCamera(fps=30)
    sent = []

    async def submit(image, frame_seq, media_time_ms):
        sent.append((frame_seq, media_time_ms, base64.b64decode(image), time.monotonic()))
        await asyncio.sleep(0.04)  # Analysis time.
        return [{'id': 'person-1', 'media_time_ms': media_time_ms}]

    async def run():
        capture = CameraCapture(0, submit, opener=lambda source: camera)
        capture.start()
        await asyncio.sleep(2.5)
        view = await capture.next_view(-1)
        status = capture.status()
        capture.stop()
        return capture, view, status

    capture, view, status = asyncio.run(run())
    seqs, times = [s[0] for s in sent], [s[1] for s in sent]
    assert seqs == sorted(set(seqs)) and times == sorted(set(times)), 'Each frame is sent once, in order'
    steady = [t for t in times if t >= 500]
    rate = (len(steady) - 1) / ((steady[-1] - steady[0]) / 1000)
    assert 11 <= rate <= 13, rate
    # Newest frame: sent within about one camera frame (plus encoding) of being read.
    assert max(at - (capture.started + t / 1000) for _, t, _, at in sent) < 0.1
    assert jpeg_dimensions(sent[-1][2]) == (640, 360)
    assert view['frame_seq'] == seqs[-1] and view['overlays'] == [{'id': 'person-1', 'media_time_ms': times[-1]}]
    assert jpeg_dimensions(base64.b64decode(view['image'])) == (640, 360)
    assert status['status'] == 'live' and status['source'] == 'Webcam 0' and 25 <= status['camera_fps'] <= 32
    assert wait_until(lambda: camera.released, 1) is not None


def test_stalled_stream_goes_offline_within_3_s_and_never_repeats_a_frame():
    camera = FakeCamera(fps=30)
    sent, transitions = [], []

    async def submit(image, frame_seq, media_time_ms):
        sent.append(media_time_ms)
        return []

    async def run():
        capture = CameraCapture(0, submit, opener=lambda source: camera, on_status=transitions.append)
        capture.start()
        await asyncio.sleep(1)
        assert capture.status()['status'] == 'live'
        camera.stalled, stalled_at, before = True, time.monotonic(), len(sent)
        while capture.status()['status'] != 'offline' and time.monotonic() - stalled_at < 5:
            await asyncio.sleep(0.02)
        offline_after = time.monotonic() - stalled_at
        last = sent[-1]
        assert await capture.next_view(10**9, timeout=0.3) is None
        await asyncio.sleep(0.5)
        during = len(sent) - before
        camera.stalled = False
        resumed_at = time.monotonic()
        while capture.status()['status'] != 'live' and time.monotonic() - resumed_at < 2:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.3)
        capture.stop()
        camera.finished = True
        return offline_after, during, last

    offline_after, during, last = asyncio.run(run())
    assert offline_after < 3, offline_after
    assert during <= 1, 'Only the frame already being read when the stream stalled; nothing is re-sent'
    assert sent == sorted(set(sent)) and sent[-1] > last, 'Frames resumed, and none was analyzed twice'
    assert transitions == ['live', 'offline', 'live']


def test_capture_reconnects_when_the_camera_drops_or_cannot_open(monkeypatch):
    monkeypatch.setattr(capture_module, 'RETRY_S', 0.2)
    cameras = [FakeCamera(opened=False), FakeCamera(ends_after=10), FakeCamera()]
    opened, transitions, sent = [], [], []

    def opener(source):
        opened.append(source)
        return cameras[min(len(opened), len(cameras)) - 1]

    async def submit(image, frame_seq, media_time_ms):
        sent.append(media_time_ms)
        return []

    async def run():
        capture = CameraCapture('rtsp://nest:secret@10.0.0.5/live', submit, opener=opener, on_status=transitions.append)
        capture.start()
        await asyncio.sleep(0.15)
        first = capture.status()
        await asyncio.sleep(2.5)
        capture.stop()
        cameras[-1].finished = True
        return first

    first = asyncio.run(run())
    assert first['status'] == 'offline' and 'Could not open' in first['error'] and 'secret' not in json.dumps(first)
    assert opened[:3] == ['rtsp://nest:secret@10.0.0.5/live'] * 3
    assert transitions == ['offline', 'live', 'offline', 'live']
    assert cameras[0].released and cameras[1].released
    assert sent == sorted(set(sent))


def test_server_camera_runs_analysis_without_a_browser(monkeypatch):
    from fastapi.testclient import TestClient
    import server.app as api
    camera = FakeCamera(fps=30)
    monkeypatch.setattr(capture_module, 'open_camera', lambda source: camera)
    with TestClient(api.app) as client:
        client.get('/api/state')
        # Fast stand-in detector: the real engine still orders, rates and overlays each frame.
        monkeypatch.setattr(api.vision, '_detect', lambda jpeg: ([{'x': .3, 'y': .2, 'width': .2, 'height': .6}], 'active'))
        try:
            assert client.get('/api/camera/frame').status_code == 404
            assert client.post('/api/source', json={'source_type': 'server_camera', 'camera': 'file:///etc/passwd'}).status_code == 422
            assert camera.count == 0 and client.get('/api/state').json()['camera']['capture'] is None
            changed = client.post('/api/source', json={'source_type': 'server_camera', 'camera': 'rtsp://nest:secret@10.0.0.5/live'})
            assert changed.status_code == 200 and changed.json()['session']['source_type'] == 'server_camera'
            session = client.post('/api/session/start').json()['session']
            # No browser: nothing posts frames, yet analysis runs at the capture rate.
            assert wait_until(lambda: client.get('/api/state').json()['camera']['analysis_fps'] >= 10, 4) is not None
            state = client.get('/api/state').json()
            assert state['camera']['health'] == 'active' and state['camera']['capture']['status'] == 'live'
            assert state['camera']['capture']['source'] == 'rtsp://nest:***@10.0.0.5/live' and 'secret' not in json.dumps(state)
            view = client.get('/api/camera/frame', params={'after': -1}).json()
            assert jpeg_dimensions(base64.b64decode(view['image'])) == (640, 360)
            overlay = view['overlays'][0]
            assert overlay['epoch'] == session['epoch'] and overlay['media_time_ms'] == view['media_time_ms'] and overlay['frame_seq'] == view['frame_seq']
            newer = client.get('/api/camera/frame', params={'after': view['frame_seq']}).json()
            assert newer['frame_seq'] > view['frame_seq'] and newer['media_time_ms'] > view['media_time_ms']
            browser = {'session_id': session['id'], 'epoch': session['epoch'], 'frame_seq': 10**9, 'media_time_ms': 0, 'image': view['image']}
            assert client.post('/api/frames', json=browser).status_code == 409
            # Paused: the picture stays live, with no overlays.
            client.post('/api/session/pause')
            # A frame already in analysis when the pause lands may still carry overlays; later ones do not.
            assert wait_until(lambda: client.get('/api/camera/frame').json()['overlays'] == [], 1) is not None
            paused = client.get('/api/camera/frame').json()
            following = client.get('/api/camera/frame', params={'after': paused['frame_seq']}).json()
            assert following['frame_seq'] > paused['frame_seq'] and following['overlays'] == []
            client.post('/api/session/start')
            # The stream stops: offline within 3 s, logged once.
            camera.stalled = True
            took = wait_until(lambda: client.get('/api/state').json()['camera']['health'] == 'offline', 5)
            assert took is not None and took < 3, took
            assert client.get('/api/state').json()['camera']['capture']['status'] == 'offline'
            # Logged on the capture's next tick (1/12 s), once.
            # Counted for this camera only: with SRC-5, other cameras log their own events.
            offline_events = lambda: sum(1 for e in client.get('/api/state').json()['events'] if e['type'] == 'camera_offline' and '10.0.0.5' in e['message'])
            assert wait_until(lambda: offline_events() == 1, 0.5) is not None
            time.sleep(0.3)
            assert offline_events() == 1
            latest = client.get('/api/camera/frame').json()['frame_seq']
            assert client.get('/api/camera/frame', params={'after': latest}).status_code == 204
            camera.stalled = False
            assert wait_until(lambda: client.get('/api/state').json()['camera']['health'] == 'active', 3) is not None
            assert 'camera_online' in [e['type'] for e in client.get('/api/state').json()['events']]
            # Another source releases the camera.
            client.post('/api/demo/scenario', json={'scenario': 'normal'})
            assert wait_until(lambda: camera.released, 1) is not None
            assert client.get('/api/state').json()['camera']['capture'] is None
            assert client.get('/api/camera/frame').status_code == 404
        finally:
            camera.finished = True
            client.post('/api/session/reset')
