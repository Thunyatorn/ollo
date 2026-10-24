import threading
import time
import cv2
import numpy as np
from nestwatch_vision.capture import FileSource, LiveSource, classify, open_source


class FakeCamera:
    """Produces numbered frames at `fps` (the number is painted into pixel [0,0] so we can see which frame arrived)."""
    def __init__(self, fps=60, fail_after=None):
        self.interval, self.n, self.fail_after = 1.0 / fps, 0, fail_after
        self.released = False

    def read(self):
        time.sleep(self.interval)
        if self.fail_after is not None and self.n >= self.fail_after:
            return False, None
        img = np.zeros((4, 4, 3), np.uint8)
        img[0, 0, 0] = self.n % 256
        self.n += 1
        return True, img

    def release(self):
        self.released = True


def test_classify_sources():
    assert classify(0) == "webcam" and classify("1") == "webcam"
    assert classify("rtsp://192.168.1.5/stream") == "url" and classify("http://phone.local:8080/video") == "url"
    assert classify("clips/room.mp4") == "file"


def test_slow_consumer_always_gets_the_newest_frame_and_the_rest_are_dropped():
    cam = FakeCamera(fps=100)
    src = LiveSource(0, open_fn=lambda: cam).start()
    got, lat = [], []
    for f in src.frames():
        lat.append(time.perf_counter() - f.t)
        got.append(f.index)
        time.sleep(0.05)                                              # we process at 20 fps; the camera runs at 100
        if len(got) == 10:
            break
    src.stop()
    assert all(b > a for a, b in zip(got, got[1:]))                   # never goes backwards
    assert got[-1] - got[0] > 25                                      # most frames were skipped, not queued
    assert src.dropped > 20
    assert max(lat) < 0.03                                            # what we process is at most ~3 camera frames old


def test_fast_consumer_sees_every_frame_once():
    src = LiveSource(0, open_fn=lambda: FakeCamera(fps=30)).start()
    idx = [f.index for _, f in zip(range(15), src.frames())]
    src.stop()
    assert idx == sorted(set(idx)) and idx[-1] - idx[0] <= len(idx) + 1   # at most the odd frame missed


def test_camera_that_drops_goes_offline_then_reconnects():
    cams = [FakeCamera(fps=100, fail_after=5), FakeCamera(fps=100)]
    opened = []

    def open_fn():
        cam = cams[min(len(opened), 1)]
        opened.append(cam)
        return cam
    src = LiveSource(0, open_fn=open_fn, reconnect_delay=0.05, offline_after=0.2).start()
    time.sleep(0.15)
    time.sleep(0.12)                                                  # the first camera died at ~0.05 s and has been silent
    assert cams[0].released                                           # the dead camera handle was freed
    time.sleep(0.4)
    assert src.reconnects >= 1 and src.online                         # a new handle is delivering frames again
    src.stop()


def test_stop_ends_the_stream_and_the_thread():
    src = LiveSource(0, open_fn=lambda: FakeCamera(fps=50)).start()
    it = src.frames()
    next(it)
    threading.Timer(0.1, src.stop).start()
    assert sum(1 for _ in it) < 50
    assert not src._thread.is_alive()


def test_video_file_gives_every_frame_in_order_with_file_timestamps(tmp_path):
    path = str(tmp_path / "t.mp4")
    w = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 48))
    for i in range(20):
        w.write(np.full((48, 64, 3), i * 10, np.uint8))
    w.release()
    frames = list(open_source(path).frames())
    assert [f.index for f in frames] == list(range(20))               # none skipped
    assert np.allclose([f.t for f in frames], np.arange(20) / 10.0)   # timestamps from the file, repeatable
    assert frames[0].image.shape == (48, 64, 3)


def test_missing_file_is_a_clear_error():
    import pytest
    with pytest.raises(FileNotFoundError):
        list(FileSource("/nonexistent/clip.mp4").frames())


def test_watch_survives_a_camera_drop_and_reports_it_once():
    opened = []

    def open_fn():                                                    # works for 5 frames, then dead for ~0.4 s, then fine
        n = len(opened)
        opened.append(n)
        return FakeCamera(fps=100, fail_after=5) if n == 0 else FakeCamera(fps=100, fail_after=0) if n < 6 else FakeCamera(fps=100)
    src = LiveSource(0, open_fn=open_fn, reconnect_delay=0.05).start()
    events = []
    got = []
    for f in src.watch(lambda: events.append("offline"), lambda: events.append("online"), timeout=0.1):
        got.append(f.index)
        if len(got) == 15:
            break
    src.stop()
    assert events == ["offline", "online"]                            # one notice each way, not one per silent 0.1 s
    assert got == sorted(set(got))                                    # no frame delivered twice
