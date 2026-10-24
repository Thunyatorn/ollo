"""Face blur and saved clips. See MATH.md section 9.

Rules, in order of importance:
 1. A frame is blurred the moment it is captured. The raw picture is never stored: only blurred, compressed frames
    live in the ring buffer.
 2. If blurring fails for any reason, the frame is dropped (fail closed), never saved as it was.
 3. Clips and key frames are written from the ring buffer only, on a background thread.
"""
from collections import deque
import logging
import os
import queue
import re
import threading
import time
import cv2
import numpy as np

from .config import EvidenceConfig
from .pose import L_EAR, L_EYE, NOSE, R_EAR, R_EYE, Person

log = logging.getLogger("nestwatch.evidence")
SAFE_REF = re.compile(r"^evt_[0-9]+_t[0-9]+$")          # the only shape a clip name may take; stops "../../" tricks
HEAD_KPS = (NOSE, L_EYE, R_EYE, L_EAR, R_EAR)


def head_box(p: Person, shape, floor: float = 0.17) -> tuple[int, int, int, int]:
    """Where to blur (MATH 9.1): centered on the head keypoints, sized from the ears, eyes or torso, never smaller than
    `floor` x the person's box height, plus a 25% margin. No head keypoint: the top 30% of the person's box."""
    h_img, w_img = shape[:2]
    x1, y1, x2, y2 = (float(v) for v in p.box)
    pts = [(p.kpts[i, 0], p.kpts[i, 1], p.kpts[i, 2]) for i in HEAD_KPS if p.kpts[i, 2] >= p.kp_floor]
    if not pts:
        box = (x1, y1, x2, y1 + 0.30 * (y2 - y1))
    else:
        w = np.array([c for _, _, c in pts])
        cx = float(np.average([u for u, _, _ in pts], weights=w))
        cy = float(np.average([v for _, v, _ in pts], weights=w))
        sizes = [floor * (y2 - y1)]
        ears, eyes = p.mid(L_EAR, R_EAR), p.mid(L_EYE, R_EYE)
        if ears:
            sizes.append(1.8 * float(np.hypot(*(p.kpts[L_EAR, :2] - p.kpts[R_EAR, :2]))))
        if eyes:
            sizes.append(3.0 * float(np.hypot(*(p.kpts[L_EYE, :2] - p.kpts[R_EYE, :2]))))
        if len(pts) >= 2:                                              # spread of whatever head points we have (bent-over heads)
            xy = np.array([(u, v) for u, v, _ in pts])
            sizes.append(1.6 * float(np.max(np.linalg.norm(xy[:, None] - xy[None], axis=2))))
        if p.torso_length:
            sizes.append(0.5 * p.torso_length)
        half = 1.25 * max(sizes) / 2
        box = (cx - half, cy - half, cx + half, cy + half)
    x1, y1, x2, y2 = box
    return (max(0, int(x1)), max(0, int(y1)), min(w_img, int(np.ceil(x2))), min(h_img, int(np.ceil(y2))))


def pixelate(region: np.ndarray, cells: int = 8) -> np.ndarray:
    """Replace a region with cells x cells blocks of average colour (MATH 9.2). What is left cannot be sharpened back."""
    h, w = region.shape[:2]
    small = cv2.resize(region, (cells, cells), interpolation=cv2.INTER_AREA)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)


def blur_box(img: np.ndarray, box, cells: int = 4) -> None:
    x1, y1, x2, y2 = box
    if x2 - x1 < 2 or y2 - y1 < 2:
        return
    region = pixelate(img[y1:y2, x1:x2], cells)
    k = max(3, int((x2 - x1) / cells) | 1)
    img[y1:y2, x1:x2] = cv2.GaussianBlur(region, (k, k), 0)


class FaceDetector:
    """A dedicated face detector (YuNet) run on every saved frame. It catches faces the pose model missed: people who
    are out of focus, cut off by the frame edge, or bending over. Its boxes are blurred in addition to the pose heads.
    It runs on the already-shrunk frame (640 px wide, about 8 ms)."""

    def __init__(self, path: str, thr: float, expand: float):
        if not os.path.exists(path):
            raise FileNotFoundError(f"face detector model not found at {path}: refusing to record clips without it (see README)")
        self.path, self.thr, self.expand = path, thr, expand
        self._det = None
        self._size = None

    def boxes(self, img: np.ndarray) -> list[tuple[int, int, int, int]]:
        h, w = img.shape[:2]
        if self._det is None or self._size != (h, w):
            self._det = cv2.FaceDetectorYN.create(self.path, "", (w, h), self.thr, 0.3, 5000)
            self._size = (h, w)
        _, found = self._det.detect(img)
        out = []
        for f in ([] if found is None else found):
            x, y, bw, bh = (float(v) for v in f[:4])
            half = max(bw, bh) * self.expand / 2
            cx, cy = x + bw / 2, y + bh / 2
            out.append((max(0, int(cx - half)), max(0, int(cy - half)), min(w, int(np.ceil(cx + half))), min(h, int(np.ceil(cy + half)))))
        return out


class HeadTrail:
    """Remembers where heads were in the last few frames, so a moving head is covered despite model latency."""

    def __init__(self, frames: int, cells: int = 4):
        self.boxes: deque = deque(maxlen=frames)
        self.cells = cells

    def blur(self, frame: np.ndarray, boxes: list) -> np.ndarray:
        out = frame.copy()                                             # never touch the caller's frame
        for box in [b for old in self.boxes for b in old] + list(boxes):
            blur_box(out, box, self.cells)
        self.boxes.append(list(boxes))
        return out


class EvidenceRecorder:
    def __init__(self, cfg: EvidenceConfig | None = None):
        self.cfg = cfg or EvidenceConfig()
        self.clips_dir = os.path.join(self.cfg.dir, "clips")
        self.keyframes_dir = os.path.join(self.cfg.dir, "keyframes")
        for d in (self.clips_dir, self.keyframes_dir):
            os.makedirs(d, exist_ok=True)
        self._faces = FaceDetector(self.cfg.face_model, self.cfg.face_thr, self.cfg.face_expand)   # raises if the model is missing
        self._trail = HeadTrail(self.cfg.trail_frames, self.cfg.blur_cells)
        self._ring: deque = deque()                                    # (t, jpeg bytes of a BLURRED frame)
        self._lock = threading.Lock()
        self._pending: list[tuple[str, float]] = []
        self._jobs: queue.Queue = queue.Queue()
        self.dropped_unblurred = 0                                     # frames thrown away because blurring failed
        self.written: list[str] = []
        self._worker = threading.Thread(target=self._write_loop, daemon=True, name="evidence-writer")
        self._worker.start()

    # ---- every frame ----------------------------------------------------------------------------
    def blurred(self, frame: np.ndarray, people: list[Person]) -> np.ndarray:
        """The blurred, shrunk copy of a frame. Shrinking comes first: only the small version is ever stored, so only it
        needs blurring (4x less work). Blur = pose heads (found at full size, scaled down) + any face the face detector sees."""
        h, w = frame.shape[:2]
        scale = min(1.0, self.cfg.width / w)
        small = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1.0 else frame
        sh, sw = small.shape[:2]
        heads = []
        for p in people:
            x1, y1, x2, y2 = head_box(p, frame.shape, self.cfg.head_floor)
            heads.append((int(x1 * scale), int(y1 * scale), min(sw, int(np.ceil(x2 * scale))), min(sh, int(np.ceil(y2 * scale)))))
        return self._trail.blur(small, heads + self._faces.boxes(small))

    def add(self, frame: np.ndarray, t: float, people: list[Person]) -> bool:
        """Blur, shrink, compress and keep. Returns False (and keeps nothing) if anything goes wrong."""
        try:
            blurred = self.blurred(frame, people)
            ok, buf = cv2.imencode(".jpg", blurred, [cv2.IMWRITE_JPEG_QUALITY, self.cfg.jpeg_quality])
            if not ok:
                raise RuntimeError("jpeg encode failed")
        except Exception:
            self.dropped_unblurred += 1                                # fail closed: this moment simply is not recorded
            log.exception("could not blur a frame; dropping it")
            return False
        with self._lock:
            self._ring.append((t, buf.tobytes()))
            horizon = t - (self.cfg.seconds_before + self.cfg.seconds_after + 1.0)
            while self._ring and self._ring[0][0] < horizon:
                self._ring.popleft()
        return True

    def trigger(self, clip_ref: str, t: float) -> bool:
        if not SAFE_REF.match(clip_ref):
            log.error("refusing clip name %r", clip_ref)
            return False
        self._pending.append((clip_ref, t))
        return True

    def tick(self, now_t: float) -> None:
        """Call every frame: starts writing a clip once its 'after' seconds have been captured."""
        ready = [(r, t) for r, t in self._pending if now_t >= t + self.cfg.seconds_after]
        self._pending = [(r, t) for r, t in self._pending if now_t < t + self.cfg.seconds_after]
        for ref, t in ready:
            lo, hi = t - self.cfg.seconds_before, t + self.cfg.seconds_after
            with self._lock:
                frames = [(ft, b) for ft, b in self._ring if lo <= ft <= hi]
            self._jobs.put((ref, t, frames))

    # ---- background writing -------------------------------------------------------------------
    def _write_loop(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            ref, t, frames = job
            try:
                self._write(ref, t, frames)
            except Exception:
                log.exception("could not write clip %s", ref)
            finally:
                self._jobs.task_done()

    def _write(self, ref: str, t: float, frames: list) -> None:
        if len(frames) < 2:
            log.warning("clip %s has %d frames, skipping", ref, len(frames))
            return
        span = max(frames[-1][0] - frames[0][0], 1e-3)
        fps = float(np.clip(len(frames) / span, 5.0, 30.0))
        first = cv2.imdecode(np.frombuffer(frames[0][1], np.uint8), cv2.IMREAD_COLOR)
        h, w = first.shape[:2]
        path = os.path.join(self.clips_dir, f"{ref}.mp4")
        tmp = path + ".part.mp4"
        vw = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"avc1"), fps, (w, h))      # H.264, plays in a browser
        if not vw.isOpened():
            raise RuntimeError("cannot open the video writer")
        try:
            for _, b in frames:
                vw.write(cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR))
        finally:
            vw.release()
        os.replace(tmp, path)                                                          # a clip appears whole or not at all
        for n, when in enumerate(np.linspace(t - 1.0, t + min(1.5, self.cfg.seconds_after), self.cfg.keyframes), start=1):
            _, b = min(frames, key=lambda f: abs(f[0] - when))
            with open(os.path.join(self.keyframes_dir, f"{ref}_{n}.jpg"), "wb") as fh:
                fh.write(b)                                                            # already blurred and compressed
        self.written.append(ref)

    def wait(self, timeout: float = 10.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self._jobs.unfinished_tasks == 0:
                return True
            time.sleep(0.02)
        return False

    def stop(self) -> None:
        self._jobs.put(None)
        self._worker.join(timeout=5.0)

    # ---- housekeeping ---------------------------------------------------------------------------
    def cleanup(self, now: float | None = None) -> int:
        """Delete clips and key frames older than the retention period. Returns how many files went."""
        cutoff = (now or time.time()) - self.cfg.retention_days * 86400
        n = 0
        for d in (self.clips_dir, self.keyframes_dir):
            for name in os.listdir(d):
                p = os.path.join(d, name)
                if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                    os.remove(p)
                    n += 1
        return n

    @property
    def buffered_frames(self) -> int:
        with self._lock:
            return len(self._ring)

    @property
    def buffered_bytes(self) -> int:
        with self._lock:
            return sum(len(b) for _, b in self._ring)
