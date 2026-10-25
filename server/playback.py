"""SRC-6: the server analyzes an uploaded video itself, every 1/ANALYSIS_FPS s of the video's own timeline, in order,
up to the dashboard's playhead. Busy analysis makes the next frame wait instead of skipping it, so a slow computer or a
hidden tab delays an alert but never loses the frames it depends on (browser sampling, SRC-2, drops them)."""
import asyncio
import base64
import math
from pathlib import Path

import cv2


class RecordedAnalyzer:
    def __init__(self, submit, fps: float = 12.0):
        """`submit(image_b64, frame_seq, media_time_ms, epoch)` returns 'ok', 'busy' (try the same frame again) or
        'stale' (this epoch is over: wait for a new playhead)."""
        self.submit, self.fps = submit, fps
        self.path: Path | None = None
        self.epoch = None
        self.target_s = -math.inf           # analyze source frames up to this video time
        self.next_s = 0.0                   # the next sample time (multiple of 1/fps)
        self.analyzed_to_ms = -1
        self._seq = 0
        self._cap = None
        self._index = 0                     # next source frame to decode
        self._src_fps = 30.0
        self._reopen = False
        self._ended = self._stale = False
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._task: asyncio.Task | None = None

    def playhead(self, path, epoch, media_time_ms: float, start_ms: float | None = None) -> None:
        t = max(0.0, media_time_ms / 1000)
        if Path(path) != self.path or epoch != self.epoch:
            # A new video or a new epoch (a seek or restart): start where playback started (start_ms, from
            # /api/session/start) even if this first playhead is late, else at the playhead. Never reuse the old epoch.
            self.path, self.epoch = Path(path), epoch
            begin = min(t, max(0.0, start_ms / 1000)) if start_ms is not None else t
            self.next_s = math.ceil(begin * self.fps - 1e-6) / self.fps
            self.target_s, self.analyzed_to_ms, self._seq = t, -1, 0
            self._reopen, self._ended, self._stale = True, False, False
        else:
            self.target_s = max(self.target_s, t)
        self._idle.clear()
        self._wake.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def idle(self) -> None:
        """Wait until everything up to the playhead is analyzed (or the video ended, or the epoch went stale)."""
        await asyncio.sleep(0)
        await self._idle.wait()

    def close(self) -> None:
        if self._task:
            self._task.cancel()
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def _decode(self, sample_s: float):
        """The first source frame at or after `sample_s`, as (time_s, base64 JPEG), or None at the end."""
        if self._reopen:
            if self._cap is not None:
                self._cap.release()
            self._cap = cv2.VideoCapture(str(self.path))
            self._src_fps = self._cap.get(cv2.CAP_PROP_FPS) or 30.0
            self._index = max(0, math.floor(sample_s * self._src_fps - 1e-6))
            if self._index:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, self._index)
            self._reopen = False
        while True:
            ok, frame = self._cap.read()
            if not ok:
                return None
            frame_s, self._index = self._index / self._src_fps, self._index + 1
            if frame_s + 1e-6 >= sample_s:
                break
        if frame.shape[1] != 640:            # the same size and quality the dashboard sends (SRC-2)
            frame = cv2.resize(frame, (640, round(640 * frame.shape[0] / frame.shape[1])))
        jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 65])[1].tobytes()
        return frame_s, base64.b64encode(jpeg).decode()

    async def _run(self) -> None:
        pending = None                       # a decoded frame waiting for a free analysis slot
        while True:
            if self._ended or self._stale or self.next_s > self.target_s + 1e-9:
                pending = None if (self._ended or self._stale) else pending
                self._idle.set()
                self._wake.clear()
                await self._wake.wait()
                continue
            epoch = self.epoch
            if pending is None or pending[0] != epoch:
                decoded = await asyncio.to_thread(self._decode, self.next_s)
                if epoch != self.epoch:
                    continue                 # a seek arrived while decoding
                if decoded is None:
                    self._ended = True
                    continue
                pending = (epoch, *decoded)
            _, frame_s, image = pending
            result = await self.submit(image, self._seq + 1, frame_s * 1000, epoch)
            if epoch != self.epoch:
                pending = None
                continue
            if result == 'busy':
                await asyncio.sleep(0.005)   # the same frame again: nothing is skipped
                continue
            if result == 'stale':
                self._stale = True
                continue
            self._seq += 1
            self.analyzed_to_ms = round(frame_s * 1000)
            self.next_s = (math.floor(frame_s * self.fps + 1e-6) + 1) / self.fps
            pending = None
