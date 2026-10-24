"""SRC-4 server-side capture: the server reads a webcam or stream itself, so analysis never depends on a browser tab.

A reader thread reads continuously and keeps only the newest frame, so camera buffers never fill and
analysis never falls behind live. An asyncio pump sends the newest unsent frame 12 times a second
through the same path as browser frames. A frame is never sent twice: a frozen stream must not look
like a still child.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import itertools
import threading
import time
from collections import deque
from urllib.parse import urlsplit

CAPTURE_FPS = 12
OFFLINE_AFTER_S = 2.0  # No new frame for this long is offline, inside the 3 s requirement.
RETRY_S = 2.0
WIDTH = 640
JPEG_QUALITY = 65  # Same encoding as the dashboard's frames.
STREAM_SCHEMES = ('rtsp', 'rtsps', 'http', 'https')
# Shared by every capture, so a new camera never reuses a frame_seq a dashboard has already seen.
_sequence = itertools.count(1)


def parse_camera(value) -> int | str:
    """A webcam index 0–9 or a stream URL. File paths and other schemes (file:, concat:…) are rejected."""
    if isinstance(value, int) and not isinstance(value, bool):
        if 0 <= value <= 9:
            return value
        raise ValueError('Webcam index must be 0–9')
    if not isinstance(value, str):
        raise ValueError('Enter a webcam index or a stream URL')
    text = value.strip()
    if text.isdigit():
        if len(text) == 1:
            return int(text)
        raise ValueError('Webcam index must be 0–9')
    if len(text) > 500 or any(c.isspace() or ord(c) < 32 for c in text):
        raise ValueError('Stream URL must be at most 500 characters, with no spaces')
    try:
        parts = urlsplit(text)
        host = parts.hostname
    except ValueError:
        raise ValueError('Invalid stream URL') from None
    if parts.scheme.lower() not in STREAM_SCHEMES or not host:
        raise ValueError('Use a webcam index (0–9) or an rtsp://, rtsps://, http:// or https:// stream URL')
    return text


def mask(source: int | str) -> str:
    """What may be shown or logged: never a URL password."""
    if isinstance(source, int):
        return f'Webcam {source}'
    parts = urlsplit(source)
    if parts.password is None:
        return source
    netloc = parts.netloc.rsplit('@', 1)
    return parts._replace(netloc=f'{parts.username}:***@{netloc[1]}').geturl()


def open_camera(source: int | str):
    """The real camera. Stream reads time out after 5 s so a dead connection is reopened."""
    import cv2
    if isinstance(source, int):
        capture = cv2.VideoCapture(source)
    else:
        capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
    with contextlib.suppress(Exception):
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def encode(image) -> bytes:
    import cv2
    height, width = image.shape[:2]
    if width != WIDTH:
        image = cv2.resize(image, (WIDTH, max(32, round(height * WIDTH / width))), interpolation=cv2.INTER_AREA)
    ok, data = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise ValueError('JPEG encoding failed')
    return data.tobytes()


class CameraCapture:
    """`submit(image_b64, frame_seq, media_time_ms)` analyzes one frame and returns its overlays, or None if it was not analyzed."""

    def __init__(self, source, submit, opener=None, fps: int = CAPTURE_FPS, on_status=None):
        self.source, self.label = source, mask(source)
        self.submit, self.opener, self.fps, self.on_status = submit, opener, fps, on_status
        self.started = time.monotonic()
        self.error = None
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._latest = None  # (number, read at, image): only the newest frame is kept.
        self._sent = 0
        self._phase, self._phase_at, self._last_read = 'connecting', self.started, None
        self._reads = deque(maxlen=64)
        self._reported = None
        self._view = None
        self._published = asyncio.Event()
        self._thread = threading.Thread(target=self._read_loop, name='camera-capture', daemon=True)
        self._pump_task = None

    def start(self):
        """Call from the running event loop."""
        self._thread.start()
        self._pump_task = asyncio.get_running_loop().create_task(self._pump())

    def stop(self):
        """Stop sending at once. The reader releases the camera after its current read returns."""
        self._stopped.set()
        if self._pump_task is not None:
            self._pump_task.cancel()

    def _set_phase(self, phase):
        with self._lock:
            self._phase, self._phase_at = phase, time.monotonic()
            self._last_read = None  # Live only once this connection delivers a frame.

    def _read_loop(self):
        number = 0
        while not self._stopped.is_set():
            self._set_phase('connecting')
            camera = None
            try:
                camera = (self.opener or open_camera)(self.source)
                if camera is None or not camera.isOpened():
                    self.error = f'Could not open {self.label}'
                else:
                    self._set_phase('reading')
                    while not self._stopped.is_set():
                        ok, image = camera.read()
                        if not ok or image is None:
                            self.error = f'{self.label} stopped sending frames'
                            break
                        number += 1
                        now = time.monotonic()
                        with self._lock:
                            self._latest = (number, now, image)
                            self._last_read = now
                            self._reads.append(now)
                        self.error = None
            except Exception as exc:  # A camera failure must never end capture; retry.
                self.error = f'{self.label}: {type(exc).__name__}'
            finally:
                if camera is not None:
                    with contextlib.suppress(Exception):
                        camera.release()
            self._set_phase('retrying')
            self._stopped.wait(RETRY_S)

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            last, reads = self._last_read, [t for t in self._reads if now - t <= 2.0]
        if self._stopped.is_set() or self._phase == 'retrying':
            state = 'offline'
        elif last is not None and now - last < OFFLINE_AFTER_S:
            state = 'live'
        elif last is None and now - self._phase_at < OFFLINE_AFTER_S:
            state = 'connecting'
        else:
            state = 'offline'
        fps = round((len(reads) - 1) / (reads[-1] - reads[0]), 1) if len(reads) >= 2 and reads[-1] > reads[0] else 0.0
        return {'source': self.label, 'status': state, 'camera_fps': fps if state == 'live' else 0.0, 'error': self.error if state != 'live' else None}

    def _report(self):
        state = self.status()['status']
        if state in ('live', 'offline') and state != self._reported:
            self._reported = state
            if self.on_status is not None:
                with contextlib.suppress(Exception):
                    self.on_status(state)

    async def _pump(self):
        period, tick = 1 / self.fps, time.monotonic()
        while not self._stopped.is_set():
            tick += period
            delay = tick - time.monotonic()
            if delay < 0:  # Analysis ran long: skip missed ticks rather than burst.
                tick, delay = time.monotonic(), 0
            await asyncio.sleep(delay)
            try:
                self._report()
                with self._lock:
                    latest = self._latest
                if latest is None or latest[0] == self._sent:
                    continue  # No new camera frame: analyze nothing.
                self._sent = latest[0]
                jpeg = await asyncio.to_thread(encode, latest[2])
                image = base64.b64encode(jpeg).decode()
                frame_seq, media_time_ms = next(_sequence), round((latest[1] - self.started) * 1000, 1)
                overlays = await self.submit(image, frame_seq, media_time_ms)
                if self._stopped.is_set():
                    return
                self._view = {'frame_seq': frame_seq, 'media_time_ms': media_time_ms, 'image': image, 'overlays': overlays or []}
                self._published.set()
                self._published = asyncio.Event()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # One bad frame never stops capture.
                self.error = f'Frame failed: {type(exc).__name__}'

    async def next_view(self, after: int = -1, timeout: float = 1.0) -> dict | None:
        """The newest published frame with frame_seq > after, waiting up to `timeout`; None if none arrives."""
        deadline = time.monotonic() + timeout
        while self._view is None or self._view['frame_seq'] <= after:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or self._stopped.is_set():
                return None
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._published.wait(), remaining)
        return self._view
