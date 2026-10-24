"""Sends each event's blurred key frames to the worker (CLUADE.md link 7): POST /keyframes, multipart, keyed by clip_ref.

Only the two or three key frames leave this computer, never video, and they are blurred before they were ever stored
(evidence.py). Uploads run on their own thread and are retried for a while; a dead worker never slows the camera loop.
"""
import logging
import queue
import threading
import time

import requests

log = logging.getLogger("nestwatch.upload")


class KeyframeUploader:
    def __init__(self, worker_url: str, token: str, attempts: int = 5, retry_s: float = 3.0, timeout: float = 5.0):
        self.url = worker_url.rstrip("/") + "/keyframes"
        self.headers = {"Authorization": f"Bearer {token}"}
        self.attempts, self.retry_s, self.timeout = attempts, retry_s, timeout
        self._q: queue.Queue = queue.Queue(maxsize=200)
        self.sent, self.failed = 0, 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="keyframe-upload")
        self._thread.start()

    def __call__(self, clip_ref: str, jpegs: list[bytes]) -> None:
        """EvidenceRecorder's on_written hook."""
        try:
            self._q.put_nowait((clip_ref, jpegs))
        except queue.Full:
            self.failed += 1
            log.warning("key frame upload queue full; %s not sent", clip_ref)

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            clip_ref, jpegs = item
            files = [("frames", (f"{clip_ref}_{n}.jpg", b, "image/jpeg")) for n, b in enumerate(jpegs[:3], 1)]
            for attempt in range(self.attempts):
                try:
                    r = requests.post(self.url, data={"clip_ref": clip_ref}, files=files, headers=self.headers, timeout=self.timeout)
                    if r.status_code == 200:
                        self.sent += 1
                        break
                    if 400 <= r.status_code < 500:          # refused (bad role or bad frames): retrying will not help
                        log.error("worker refused key frames for %s: %s %s", clip_ref, r.status_code, r.text[:120])
                        self.failed += 1
                        break
                except requests.RequestException as e:
                    log.warning("worker unreachable for %s (try %d): %s", clip_ref, attempt + 1, e)
                time.sleep(self.retry_s)
            else:
                self.failed += 1

    def stop(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=2.0)
