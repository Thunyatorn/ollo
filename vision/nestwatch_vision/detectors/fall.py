"""Fall detection from pose, in the picture (no calibration needed). See MATH.md section 8.1.

A fall = a FAST downward drop of the body, relative to the person's own standing height, followed by staying in a
genuinely LOW or HORIZONTAL position. Each part answers a failure seen on real footage (OmniFall / GMDCSA24):
 * sitting down onto a bed or chair ends upright and only somewhat shorter: not "low", so not a fall
 * lying down on purpose is slower than a fall: the drop has to happen within `drop_window_s`
 * the pose model briefly loses a person on the floor: short gaps do not reset the "low" timer
Heights are measured in the person's own standing height, so the rule works near and far from the camera.
"""
from collections import deque
from dataclasses import dataclass, field
import math
import numpy as np

from ..pose import L_HIP, L_SHOULDER, R_HIP, R_SHOULDER


@dataclass
class FallConfig:
    """Defaults chosen on OmniFall/GMDCSA24 Subjects 1-3 by the WORST subject's F1 (MATH.md 8.1). PROVISIONAL: on the one
    unseen subject they caught 9 of 17 falls with 3 false alarms; they must be re-checked on footage neither of us tuned on."""
    min_conf: float = 0.1            # use low-confidence people too: a person on the floor often scores low
    drop_frac: float = 0.45          # the top of the body drops by this fraction of standing height ...
    drop_window_s: float = 1.5       # ... within this time
    low_height_frac: float = 0.65    # "low": box height under this fraction of standing height
    low_aspect: float = 1.1          # or wider than tall
    lying_angle: float = 60.0        # or torso this far from vertical (degrees)
    hold_s: float = 0.8              # low for this long ...
    recent_drop_s: float = 3.0       # ... with the drop at most this long before the low phase began
    gap_tolerance_s: float = 0.5     # missing detections up to this long do not reset "low"
    refractory_s: float = 10.0       # one alert per fall
    max_gap_s: float = 1.0           # a track unseen this long is forgotten
    # The reference build's second path (commit 17cca7a, server/events.py "path B"): the body height collapses and the person
    # stays low, not wide, having started with a hand at the floor (a fall onto hands and knees, toward the camera).
    # Off by default: measured in MATH.md 8.1c.
    collapse_path: bool = False
    collapse_from: float = 0.85      # height was at least this share of standing height ...
    collapse_to: float = 0.70        # ... and fell to this share or less ...
    collapse_window_s: float = 1.5   # ... within this time
    collapse_low: float = 0.75       # then stays at or below this share
    collapse_hold_s: float = 1.5
    hand_floor: float = 0.15         # a wrist within this share of standing height above the box bottom


@dataclass
class FallEvent:
    track: int
    t: float
    box: np.ndarray
    info: dict = field(default_factory=dict)      # measurements at the moment it fired (for analysis; not used by the rule)


@dataclass
class _Track:
    id: int
    box: np.ndarray
    last_t: float
    hist: deque = field(default_factory=lambda: deque(maxlen=120))       # (t, top_y, height)
    upright: deque = field(default_factory=lambda: deque(maxlen=40))     # heights seen while clearly upright
    drop_at: float = -math.inf
    low_since: float | None = None
    low_seen: float = -math.inf
    fired_at: float = -math.inf
    collapse_at: float = -math.inf
    hands_since: float | None = None
    hands_seen: float = -math.inf

    def standing_height(self) -> float:
        if self.upright:
            return float(np.median(self.upright))
        return max(h for _, _, h in self.hist)                           # no clear upright view yet: tallest seen


def _torso_angle(kpts, floor=0.3):
    s = [kpts[i] for i in (L_SHOULDER, R_SHOULDER) if kpts[i, 2] >= floor]
    h = [kpts[i] for i in (L_HIP, R_HIP) if kpts[i, 2] >= floor]
    if not s or not h:
        return None
    sx, sy = np.mean([p[0] for p in s]), np.mean([p[1] for p in s])
    hx, hy = np.mean([p[0] for p in h]), np.mean([p[1] for p in h])
    return math.degrees(math.atan2(abs(hx - sx), max(hy - sy, 1e-6))) if hy > sy else 90.0 + math.degrees(math.atan2(sy - hy, abs(hx - sx) + 1e-6))


def _measure(tr, p, t, h, w, H, angle) -> dict:
    """Body measurements at the moment of an alert, for analysis (the rule does not read them)."""
    k, y2 = p.kpts, float(p.box[3])
    ok = lambda ids, floor=0.3: [float(k[i, 1]) for i in ids if k[i, 2] >= floor]
    hips, nose, ankles = ok((L_HIP, R_HIP)), ok((0,)), ok((15, 16))
    hist = [(tt, top) for tt, top, _ in tr.hist if t - 3.0 <= tt <= t]
    speed = max([(b[1] - a[1]) / H / (b[0] - a[0]) for i, a in enumerate(hist) for b in hist[i + 1:] if b[0] - a[0] >= 0.25] or [0.0])
    tops = [top for _, top in hist]
    return {"h_ratio": h / H, "aspect": w / h, "angle": angle, "since_low": None if tr.low_since is None else t - tr.low_since, "drop_lag": t - tr.drop_at,
            "peak_speed": speed,                                                          # fastest downward move of the top, standing heights per second
            "drop_total": (tops[-1] - min(tops)) / H if tops else 0.0,                    # how far the top fell in the last 3 s
            "hip_rel": (y2 - np.mean(hips)) / h if hips else None,                       # hip height above the box bottom, in box heights
            "head_rel": (y2 - nose[0]) / h if nose else None,                             # head height above the box bottom
            "kpt_conf": float(np.mean(k[:, 2])), "ankle_vis": float(np.mean(k[15:17, 2])), "box_conf": float(p.box_conf)}


def _iou(a, b):
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


class FallDetector:
    def _collapse(self, tr, p, t, h, w, H) -> bool:
        """Path B: a collapse of the box height, then low and not lying wide, begun with a hand at the floor."""
        c = self.cfg
        recent = [hh for tt, _, hh in tr.hist if t - c.collapse_window_s <= tt <= t]
        if recent and max(recent) >= c.collapse_from * H and h <= c.collapse_to * H:
            tr.collapse_at = t
        y2 = float(p.box[3])
        hand = any(p.kpts[i, 2] >= 0.3 and float(p.kpts[i, 1]) >= y2 - c.hand_floor * H for i in (9, 10))
        low = h <= c.collapse_low * H and w / h <= c.low_aspect
        if low and (hand or tr.hands_since is not None):
            tr.hands_since, tr.hands_seen = (tr.hands_since if tr.hands_since is not None else t), t
        elif tr.hands_since is not None and t - tr.hands_seen > c.gap_tolerance_s:
            tr.hands_since = None
        return tr.hands_since is not None and t - tr.hands_since >= c.collapse_hold_s and t - tr.collapse_at <= 3.0

    def __init__(self, cfg: FallConfig | None = None):
        self.cfg = cfg or FallConfig()
        self.tracks: list[_Track] = []
        self._next = 1

    def _associate(self, boxes, t):
        """Greedy matching in the picture: overlap first, then nearness relative to the person's size."""
        pairs = []
        for ti, tr in enumerate(self.tracks):
            for bi, b in enumerate(boxes):
                iou = _iou(tr.box, b)
                h = max(tr.box[3] - tr.box[1], 1.0)
                d = math.hypot((tr.box[0] + tr.box[2] - b[0] - b[2]) / 2, (tr.box[1] + tr.box[3] - b[1] - b[3]) / 2) / h
                if iou > 0.1 or d < 0.6:
                    pairs.append((-(iou - 0.3 * d), ti, bi))
        used_t, used_b, match = set(), set(), {}
        for _, ti, bi in sorted(pairs):
            if ti not in used_t and bi not in used_b:
                used_t.add(ti); used_b.add(bi); match[bi] = self.tracks[ti]
        for bi, b in enumerate(boxes):
            if bi not in match:
                tr = _Track(self._next, b, t); self._next += 1
                self.tracks.append(tr); match[bi] = tr
        return match

    def update(self, people, t: float) -> list[FallEvent]:
        c = self.cfg
        people = [p for p in people if p.box_conf >= c.min_conf]
        match = self._associate([p.box for p in people], t)
        events = []
        for bi, p in enumerate(people):
            tr = match[bi]
            x1, y1, x2, y2 = (float(v) for v in p.box)
            w, h = max(x2 - x1, 1.0), max(y2 - y1, 1.0)
            angle = _torso_angle(p.kpts)
            if (angle is not None and angle < 30 and h / w > 1.3) or (angle is None and h / w > 2.0):
                tr.upright.append(h)
            tr.box, tr.last_t = p.box, t
            tr.hist.append((t, y1, h))
            H = tr.standing_height()
            recent = [top for tt, top, _ in tr.hist if t - c.drop_window_s <= tt < t]
            if recent and (y1 - min(recent)) / H >= c.drop_frac:
                tr.drop_at = t
            low = h / H < c.low_height_frac or w / h > c.low_aspect or (angle is not None and angle > c.lying_angle)
            if low:
                if tr.low_since is None or t - tr.low_seen > c.gap_tolerance_s:
                    tr.low_since = t
                tr.low_seen = t
            elif t - tr.low_seen > c.gap_tolerance_s:
                tr.low_since = None
            # The body tilts first (low by angle or width) and the top drops a moment later, so the drop may come just
            # before OR during the low phase; it just has to belong to this episode.
            path_b = c.collapse_path and self._collapse(tr, p, t, h, w, H)
            if ((path_b or (tr.low_since is not None and t - tr.low_since >= c.hold_s and tr.low_since - c.recent_drop_s <= tr.drop_at <= t))
                    and t - tr.fired_at > c.refractory_s):
                tr.fired_at = t
                events.append(FallEvent(tr.id, t, p.box, _measure(tr, p, t, h, w, H, angle)))
        self.tracks = [tr for tr in self.tracks if t - tr.last_t <= c.max_gap_s]
        return events
