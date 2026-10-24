"""PRV-3 evidence clips: the analyzed frames around an incident, heads blurred, kept locally for a limited time."""
from __future__ import annotations

import time
from collections import deque
from pathlib import Path

from .review import blur_heads

BEFORE_MS = 5000
AFTER_MS = 5000


class ClipRecorder:
    """Rolling 5 s pre-buffer; a started clip collects until 5 s after its start, then is returned as finished."""

    def __init__(self, before_ms: int = BEFORE_MS, after_ms: int = AFTER_MS):
        self.before_ms, self.after_ms = before_ms, after_ms
        self.buffer: deque = deque()
        self.pending: dict = {}

    def add(self, media_time_ms: float, jpeg: bytes, people: list[dict]) -> list[tuple[str, list[dict]]]:
        frame = {'media_time_ms': media_time_ms, 'jpeg': jpeg, 'people': people}
        self.buffer.append(frame)
        while self.buffer and media_time_ms - self.buffer[0]['media_time_ms'] > self.before_ms:
            self.buffer.popleft()
        finished = []
        for incident_id, clip in list(self.pending.items()):
            if not clip['frames'] or clip['frames'][-1] is not frame:
                clip['frames'].append(frame)
            if media_time_ms >= clip['until']:
                finished.append((incident_id, self.pending.pop(incident_id)['frames']))
        return finished

    def start(self, incident_id: str, media_time_ms: float):
        if incident_id not in self.pending:
            self.pending[incident_id] = {'frames': list(self.buffer), 'until': media_time_ms + self.after_ms}

    def flush(self) -> list[tuple[str, list[dict]]]:
        """Finalize every clip in progress with the frames it has (session reset, stop, source change)."""
        finished = [(incident_id, clip['frames']) for incident_id, clip in self.pending.items() if clip['frames']]
        self.pending, self.buffer = {}, deque()
        return finished


def write_clip(path: Path, frames: list[dict]) -> bool:
    """VP8 WebM at the frames' own rate (1–30 fps), every head blurred. False if nothing could be written."""
    import cv2
    import numpy as np
    images = [cv2.imdecode(np.frombuffer(f['jpeg'], dtype=np.uint8), cv2.IMREAD_COLOR) for f in frames]
    pairs = [(f, image) for f, image in zip(frames, images) if image is not None]
    if not pairs:
        return False
    span = (pairs[-1][0]['media_time_ms'] - pairs[0][0]['media_time_ms']) / 1000
    fps = min(30.0, max(1.0, (len(pairs) - 1) / span)) if span > 0 else 12.0
    height, width = pairs[0][1].shape[:2]
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'VP80'), round(fps, 2), (width, height))
    if not writer.isOpened():
        return False
    for frame, image in pairs:
        if image.shape[:2] != (height, width):
            image = cv2.resize(image, (width, height))
        writer.write(blur_heads(image, frame['people']))
    writer.release()
    return path.is_file() and path.stat().st_size > 0


def blur_jpeg(jpeg: bytes, people: list[dict]) -> bytes:
    """Evidence still with heads blurred."""
    import cv2
    import numpy as np
    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return jpeg
    ok, encoded = cv2.imencode('.jpg', blur_heads(image, people), [cv2.IMWRITE_JPEG_QUALITY, 85])
    return encoded.tobytes() if ok else jpeg


def prune(data_dir: Path, days: float, store, now: float | None = None) -> list[str]:
    """Delete clips and stills older than `days` and remove their links from incidents."""
    cutoff = (now or time.time()) - days * 86400
    candidates = list((data_dir / 'clips').glob('*.webm')) + list(data_dir.glob('*.jpg'))
    removed = [path.name for path in candidates if path.stat().st_mtime < cutoff]
    for path in candidates:
        if path.name in removed:
            path.unlink(missing_ok=True)
    if removed:
        gone = set(removed)
        with store.lock, store.db:
            for incident in store.incidents():
                changed = False
                for key in ('clip_url', 'evidence_url'):
                    if incident.get(key, '').rsplit('/', 1)[-1] in gone:
                        incident.pop(key)
                        changed = True
                if changed:
                    store.save_incident(incident)
    return removed
