"""Pose model wrapper, keypoint helpers and smoothing. See MATH.md sections 1.7 and 2."""
from dataclasses import dataclass
import math
import numpy as np

from .config import PoseConfig

# COCO keypoint indexes (MATH 2)
NOSE, L_EYE, R_EYE, L_EAR, R_EAR = 0, 1, 2, 3, 4
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW, L_WRIST, R_WRIST = 5, 6, 7, 8, 9, 10
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANKLE, R_ANKLE = 11, 12, 13, 14, 15, 16


@dataclass
class Person:
    box: np.ndarray            # (x1, y1, x2, y2) pixels
    box_conf: float
    kpts: np.ndarray           # (17, 3): u, v, confidence
    kp_floor: float = 0.3

    def kp(self, i: int):
        """(u, v) of keypoint i, or None if the model is not confident about it."""
        u, v, c = self.kpts[i]
        return (float(u), float(v)) if c >= self.kp_floor else None

    def mid(self, a: int, b: int):
        """Midpoint of two keypoints; None unless both are confident."""
        pa, pb = self.kp(a), self.kp(b)
        return None if pa is None or pb is None else ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)

    @property
    def torso_length(self):
        """Shoulder midpoint to hip midpoint, in pixels: the unit that makes pose measurements size-independent (MATH 2)."""
        s, h = self.mid(L_SHOULDER, R_SHOULDER), self.mid(L_HIP, R_HIP)
        return None if s is None or h is None else math.hypot(h[0] - s[0], h[1] - s[1])


@dataclass
class FootPoint:
    u: float
    v: float
    quality: str               # ankles | one_ankle | box_bottom  (measurement noise grows in that order, MATH 3.3)


def foot_point(p: Person) -> FootPoint:
    """The pixel to push through the homography: the feet are on the floor, the box center is not (MATH 1.7)."""
    la, ra = p.kp(L_ANKLE), p.kp(R_ANKLE)
    if la and ra:
        return FootPoint((la[0] + ra[0]) / 2, (la[1] + ra[1]) / 2, "ankles")
    if la or ra:
        a = la or ra
        return FootPoint(a[0], a[1], "one_ankle")
    x1, _, x2, y2 = p.box
    return FootPoint(float((x1 + x2) / 2), float(y2), "box_bottom")


def box_iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return float(inter / union) if union > 0 else 0.0


def dedupe(people: list[Person], iou: float = 0.55) -> list[Person]:
    """Drop the weaker of two detections that are the same person (the nano model produced one on the sample photo, IoU 0.68).

    IoU only, never "mostly inside": a small child standing right in front of an adult sits entirely inside the
    adult's box (IoU about 0.3) and must survive.
    """
    keep: list[Person] = []
    for p in sorted(people, key=lambda q: -q.box_conf):
        if all(box_iou(p.box, q.box) <= iou for q in keep):
            keep.append(p)
    return keep


def resolve_device(device: str) -> str:
    if device != "auto":
        return device
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


class PoseModel:
    def __init__(self, cfg: PoseConfig | None = None):
        from ultralytics import YOLO                       # imported here so the rest of the package works without torch
        self.cfg = cfg or PoseConfig()
        self.device = resolve_device(self.cfg.device)
        self.model = YOLO(self.cfg.weights)
        self.warmup()

    def warmup(self) -> None:
        """The first call compiles for the GPU and takes about a second; do it at start-up, not on the first child."""
        blank = np.zeros((self.cfg.imgsz, self.cfg.imgsz, 3), np.uint8)
        for _ in range(3):
            self.model(blank, imgsz=self.cfg.imgsz, device=self.device, verbose=False)

    def infer(self, image: np.ndarray) -> list[Person]:
        """People confident enough to track (conf 0.25)."""
        return [p for p in self.infer_all(image) if p.box_conf >= self.cfg.conf]

    def infer_all(self, image: np.ndarray) -> list[Person]:
        """Everyone the model is even slightly sure about (conf 0.1). Used for blurring: a face we are unsure is a person
        is still a face we do not want in a saved clip. Tracking uses `infer`."""
        r = self.model(image, imgsz=self.cfg.imgsz, conf=min(self.cfg.conf, self.cfg.blur_conf), device=self.device, verbose=False)[0]
        if r.keypoints is None or len(r.boxes) == 0:
            return []
        boxes = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        kpts = r.keypoints.data.cpu().numpy()
        return dedupe([Person(boxes[i], float(confs[i]), kpts[i], self.cfg.kp_floor) for i in range(len(boxes))])


class OneEuro:
    """One-Euro filter (Casiez et al. 2012): heavy smoothing when still, light smoothing when moving fast (MATH 2).

    min_cutoff (Hz) sets the smoothing of a still point; beta raises the cutoff with speed. Start values for pixel
    coordinates at 15 to 30 fps; tune on real footage.
    """

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02, d_cutoff: float = 1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self._x = self._dx = self._t = self._raw = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t: float):
        x = np.asarray(x, dtype=float)
        if self._x is None:
            self._x, self._dx, self._t, self._raw = x, np.zeros_like(x), t, x
            return x
        dt = max(t - self._t, 1e-3)
        dx = (x - self._raw) / dt
        a_d = self._alpha(self.d_cutoff, dt)
        self._dx = a_d * dx + (1 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * np.abs(self._dx)
        a = self._alpha(cutoff, dt)
        self._x = a * x + (1 - a) * self._x
        self._raw, self._t = x, t
        return self._x
