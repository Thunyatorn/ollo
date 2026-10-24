"""PRV-3 evidence clips: 5 s before/after, heads blurred, partial finalize, retention."""
import os
import time

import cv2
import numpy as np
from server.clips import ClipRecorder, prune, write_clip
from server.store import Store
from server.tests.test_events import ASPECT, skeleton


def checker_jpeg():
    """8-px checkerboard: coarse enough to survive VP8 compression, so blur is measurable."""
    board = ((np.indices((360, 640)) // 8).sum(axis=0) % 2 * 255).astype(np.uint8)
    _, raw = cv2.imencode('.jpg', cv2.cvtColor(board, cv2.COLOR_GRAY2BGR), [cv2.IMWRITE_JPEG_QUALITY, 95])
    return raw.tobytes()


def feed(recorder, seconds, start=0.0, fps=12, start_at=None, incident='i1'):
    jpeg, person = checker_jpeg(), {**skeleton(x0=0.9, top=0.15), 'track_id': 1}
    finished = []
    for n in range(int(seconds * fps)):
        t = int((start + n / fps) * 1000)
        if start_at is not None and t >= start_at * 1000 and incident not in recorder.pending:
            recorder.start(incident, t)
        finished += recorder.add(t, jpeg, [person])
    return finished, person


def test_clip_covers_before_and_after_and_blurs_heads(tmp_path):
    recorder = ClipRecorder()
    finished, person = feed(recorder, 14, start_at=6.0)
    assert [incident for incident, _ in finished] == ['i1']
    frames = finished[0][1]
    span = frames[-1]['media_time_ms'] - frames[0]['media_time_ms']
    assert 9500 <= span <= 10100 and 115 <= len(frames) <= 122  # 5 s before + 5 s after at 12 fps.
    path = tmp_path / 'i1.webm'
    assert write_clip(path, frames)
    capture = cv2.VideoCapture(str(path))
    count, fps = capture.get(cv2.CAP_PROP_FRAME_COUNT), capture.get(cv2.CAP_PROP_FPS)
    ok, image = capture.read()
    capture.release()
    assert ok and abs(fps - 12) < 0.5 and (count <= 0 or abs(count - len(frames)) <= 2)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(float)
    nose = person['keypoints'][0]
    hx, hy = int(nose[0] * 640), int(nose[1] * 360)
    head = gray[hy - 6:hy + 6, hx - 6:hx + 6]
    hip = person['keypoints'][11]
    torso = gray[int(hip[1] * 360) - 30:int(hip[1] * 360) - 18, int(hip[0] * 640) - 6:int(hip[0] * 640) + 6]
    assert head.std() < 0.5 * torso.std()  # Head blurred; body region keeps the pattern.


def test_reset_finalizes_partial_clip(tmp_path):
    recorder = ClipRecorder()
    finished, _ = feed(recorder, 3, start_at=2.0, incident='i2')
    assert finished == []
    flushed = recorder.flush()
    assert [incident for incident, _ in flushed] == ['i2']
    frames = flushed[0][1]
    assert 2900 <= frames[-1]['media_time_ms'] - frames[0]['media_time_ms'] + 1000 / 12 <= 3100
    assert write_clip(tmp_path / 'i2.webm', frames) and recorder.pending == {}


def test_retention_deletes_files_and_links(tmp_path):
    store = Store(tmp_path / 'test.sqlite3')
    clips = tmp_path / 'clips'
    clips.mkdir()
    old, new, still = clips / 'old.webm', clips / 'new.webm', tmp_path / 'oldstill.jpg'
    for path in (old, new, still):
        path.write_bytes(b'x')
    ten_days = time.time() - 10 * 86400
    os.utime(old, (ten_days, ten_days))
    os.utime(still, (ten_days, ten_days))
    incident = store.observe('fall', ['Drop'], 'local_rule')
    incident.update(clip_url='/api/clips/old.webm', evidence_url='/api/media/oldstill.jpg')
    with store.db:
        store.save_incident(incident)
    removed = prune(tmp_path, days=7, store=store)
    assert sorted(removed) == ['old.webm', 'oldstill.jpg']
    assert not old.exists() and not still.exists() and new.exists()
    current = store.incident(incident['id'])
    assert 'clip_url' not in current and 'evidence_url' not in current
