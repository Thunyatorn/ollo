"""SRC-6: uploaded videos are analyzed by the server, every 1/12 s frame, following the dashboard's playhead."""
import asyncio
import base64
import os
import random
import tempfile
import time

os.environ.setdefault('DATA_DIR', tempfile.mkdtemp(prefix='lookout-test-'))
import cv2
import numpy as np
from fastapi.testclient import TestClient
from server.app import app
from server.playback import RecordedAnalyzer


def write_video(path, seconds=2.0, fps=24):
    """Each frame's gray level is its index, so a test can tell which source frame was analyzed."""
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (160, 120))
    for i in range(int(seconds * fps)):
        writer.write(np.full((120, 160, 3), min(255, i * 5), dtype=np.uint8))
    writer.release()
    return path


class Recorder:
    """A stand-in for the vision path: sometimes busy, sometimes slow, records what it analyzed."""

    def __init__(self, busy_rate=0.0, stale_epochs=()):
        self.seen, self.busy_rate, self.stale_epochs = [], busy_rate, set(stale_epochs)
        self.rng = random.Random(7)

    async def __call__(self, image, frame_seq, media_time_ms, epoch):
        assert base64.b64decode(image)[:2] == b'\xff\xd8'              # a JPEG, like the dashboard's frames
        if epoch in self.stale_epochs:
            return 'stale'
        if self.rng.random() < self.busy_rate:
            return 'busy'
        await asyncio.sleep(self.rng.random() * 0.004)                  # analysis takes a while
        self.seen.append((epoch, frame_seq, round(media_time_ms)))
        return 'ok'


def test_every_frame_in_order_even_when_analysis_is_busy(tmp_path):
    path = write_video(tmp_path / 'clip.mp4')
    record = Recorder(busy_rate=0.4)
    async def run():
        analyzer = RecordedAnalyzer(record, fps=12.0)
        analyzer.playhead(path, epoch=1, media_time_ms=0)             # playback starts
        analyzer.playhead(path, epoch=1, media_time_ms=5000)          # past the end: analyze the whole clip
        await analyzer.idle()
        return analyzer
    analyzer = asyncio.run(run())
    times = [t for _, _, t in record.seen]
    assert times == [round(k * 1000 / 12) for k in range(24)]           # every 1/12 s of a 2 s clip, none skipped or doubled
    seqs = [s for _, s, _ in record.seen]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    assert analyzer.analyzed_to_ms == round(23 * 1000 / 12)


def test_pause_and_seek_follow_the_playhead(tmp_path):
    path = write_video(tmp_path / 'clip.mp4')
    record = Recorder(stale_epochs={3})
    async def run():
        analyzer = RecordedAnalyzer(record, fps=12.0)
        analyzer.playhead(path, epoch=1, media_time_ms=0)
        analyzer.playhead(path, epoch=1, media_time_ms=500)
        await analyzer.idle()
        paused = list(record.seen)
        analyzer.playhead(path, epoch=1, media_time_ms=500)            # paused: same playhead, nothing new
        await analyzer.idle()
        assert record.seen == paused
        analyzer.playhead(path, epoch=2, media_time_ms=1500)           # seek: a new epoch at 1.5 s
        analyzer.playhead(path, epoch=2, media_time_ms=1750)
        await analyzer.idle()
        analyzer.playhead(path, epoch=3, media_time_ms=1900)           # the server says this epoch is stale
        await analyzer.idle()
        return paused
    paused = asyncio.run(run())
    assert [t for _, _, t in paused] == [round(k * 1000 / 12) for k in range(7)]          # 0 … 500 ms, then it stops
    after = [(e, t) for e, _, t in record.seen[len(paused):]]
    assert after == [(2, 1500), (2, 1583), (2, 1667), (2, 1750)]          # restarts exactly at the seek; old epoch never counts


def test_playhead_endpoint_analyzes_only_recordings(tmp_path):
    path = write_video(tmp_path / 'clip.mp4', seconds=1.0, fps=10)
    with TestClient(app) as client:
        client.get('/api/state')
        state = client.post('/api/video', files={'file': ('clip.mp4', path.read_bytes(), 'video/mp4')}).json()
        state = client.post('/api/session/start', json={'media_time_ms': 0}).json()   # playback starts at 0 …
        session = state['session']
        frame = {'session_id': session['id'], 'epoch': session['epoch'], 'frame_seq': 1, 'media_time_ms': 0,
                 'image': base64.b64encode(cv2.imencode('.jpg', np.zeros((120, 160, 3), np.uint8))[1].tobytes()).decode()}
        assert client.post('/api/frames', json=frame).status_code == 409                 # recordings are read by the server
        head = {'session_id': session['id'], 'epoch': session['epoch'], 'media_time_ms': 900}   # … first heard at 0.9 s (a late tab)
        deadline, reply = time.time() + 20, {}
        while time.time() < deadline:
            reply = client.post('/api/playhead', json=head).json()
            if reply.get('analyzed_to_ms', -1) >= 800:
                break
            time.sleep(0.1)
        assert reply['analyzed_to_ms'] >= 800 and 'overlays' in reply
        assert client.get('/api/state').json()['session']['frame_seq'] >= 10            # from 0 ms, not from 0.9 s
        client.post('/api/demo/scenario', json={'scenario': 'normal'})
        session = client.get('/api/state').json()['session']
        assert client.post('/api/playhead', json={**head, 'session_id': session['id'], 'epoch': session['epoch']}).status_code == 409
        client.post('/api/session/reset')
