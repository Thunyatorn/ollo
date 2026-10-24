"""Camera and video readers. See MATH.md section 10.

Live cameras (webcam, RTSP, phone) are read on a thread that keeps only the NEWEST frame: if processing is slow we
skip frames instead of falling behind, so alerts never run on old pictures. Video files are read in order, none
skipped, with timestamps taken from the file so replays are repeatable.
"""
from dataclasses import dataclass
import threading
import time
from typing import Callable, Iterator
import cv2
import numpy as np


@dataclass
class Frame:
    image: np.ndarray          # BGR
    t: float                   # capture time in seconds (live: monotonic clock; file: position in the video)
    index: int                 # frame counter from the source; gaps mean frames were dropped


def classify(source) -> str:
    """'webcam' for 0, '0'; 'url' for rtsp/http(s); otherwise 'file'."""
    s = str(source)
    if s.isdigit():
        return "webcam"
    if s.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")):
        return "url"
    return "file"


class FileSource:
    def __init__(self, path: str, realtime: bool = False, loop: bool = False):
        self.path, self.realtime, self.loop = path, realtime, loop         # loop: start again at the end (a demo that keeps playing)

    def frames(self) -> Iterator[Frame]:
        cap = cv2.VideoCapture(self.path)
        if not cap.isOpened():
            raise FileNotFoundError(f"cannot open video {self.path}")
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        start, i = time.perf_counter(), 0
        try:
            while True:
                ok, img = cap.read()
                if not ok and self.loop and i > 0:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)                  # time keeps counting up across the restart
                    ok, img = cap.read()
                if not ok:
                    return
                if self.realtime:                                    # pace the replay like a live camera
                    delay = start + i / fps - time.perf_counter()
                    if delay > 0:
                        time.sleep(delay)
                yield Frame(img, i / fps, i)
                i += 1
        finally:
            cap.release()

    def stop(self) -> None:
        pass


class LiveSource:
    """Reader thread that keeps only the newest frame and reconnects if the camera drops."""

    def __init__(self, source, open_fn: Callable | None = None, reconnect_delay: float = 1.0, offline_after: float = 3.0):
        self.source = int(source) if str(source).isdigit() else source
        self._open = open_fn or (lambda: cv2.VideoCapture(self.source))
        self.reconnect_delay, self.offline_after = reconnect_delay, offline_after
        self._lock, self._new = threading.Lock(), threading.Condition()
        self._latest: Frame | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.read_count = self.delivered = 0
        self.last_ok = time.perf_counter()
        self.reconnects = 0

    @property
    def online(self) -> bool:
        return time.perf_counter() - self.last_ok < self.offline_after

    @property
    def dropped(self) -> int:
        return self.read_count - self.delivered

    def start(self) -> "LiveSource":
        self._thread = threading.Thread(target=self._run, daemon=True, name="capture")
        self._thread.start()
        return self

    def _run(self) -> None:
        cap = self._open()
        while not self._stop.is_set():
            ok, img = cap.read() if cap is not None else (False, None)
            if not ok:
                if cap is not None:
                    cap.release()
                self._stop.wait(self.reconnect_delay)                # camera dropped: wait, then try again
                if self._stop.is_set():
                    return
                cap = self._open()
                self.reconnects += 1
                continue
            now = time.perf_counter()
            self.last_ok = now
            with self._new:
                self._latest = Frame(img, now, self.read_count)       # overwrites any frame nobody picked up
                self.read_count += 1
                self._new.notify_all()
        if cap is not None:
            cap.release()

    def frames(self, timeout: float = 2.0, after: int = -1) -> Iterator[Frame]:
        """Yield the newest frame each time there is one (newer than index `after`). Ends when the camera has been silent for `timeout`."""
        last = after
        while not self._stop.is_set():
            with self._new:
                if not self._new.wait_for(lambda: self._latest is not None and self._latest.index != last, timeout):
                    return
                f = self._latest
            last = f.index
            self.delivered += 1
            yield f

    def watch(self, on_offline: Callable[[], None], on_online: Callable[[], None], after: int = -1,
              timeout: float = 2.0) -> Iterator[Frame]:
        """Frames that survive camera drops: when the camera goes silent, on_offline() once, keep waiting (the reader
        thread reconnects), and on_online() when frames come back. Ends only when stopped."""
        down = False
        while not self._stop.is_set():
            for f in self.frames(timeout, after):
                after = f.index
                if down:
                    down = False
                    on_online()
                yield f
            if not self._stop.is_set() and not down:
                down = True
                on_offline()

    def stop(self) -> None:
        self._stop.set()
        with self._new:
            self._new.notify_all()
        if self._thread:
            self._thread.join(timeout=2.0)


def open_source(source, realtime: bool = False, loop: bool = False):
    """A webcam index, an rtsp/http URL, or a video file path. Live sources need .start() before .frames()."""
    kind = classify(source)
    return FileSource(str(source), realtime, loop) if kind == "file" else LiveSource(source)
