"""Pose rules ported from the team's reference build (commit 17cca7a, server/events.py; its spec DET-5, DET-7, DET-8):

  possible_distress   both wrists at the throat, sustained (the universal choking sign)       high
  rhythmic_movement   two or more limbs moving back and forth at 1-5 Hz for several seconds    high
  stillness           almost no movement for `stillness_s`, outside nap time                   medium

These are "check now" signals, never diagnoses: eating, touching the neck, dancing, play and a child watching something
quietly can look the same. Measurements are in the person's own torso lengths, so they do not depend on the distance
from the camera, and evidence builds up over time (time-weighted CUSUM or explicit durations) so one noisy frame never
alerts. The thresholds are the reference build's; they have NOT been measured on labelled choking or seizure footage,
because there is none in the datasets we use (MATH.md 8.6 records what was measured).
"""
from collections import deque
from dataclasses import dataclass, field
import math

import numpy as np

from ..pose import L_ANKLE, L_HIP, L_SHOULDER, L_WRIST, NOSE, R_ANKLE, R_HIP, R_SHOULDER, R_WRIST, Person

LIMBS = (L_WRIST, R_WRIST, L_ANKLE, R_ANKLE)
KEY = (NOSE, L_SHOULDER, R_SHOULDER, L_WRIST, R_WRIST, L_HIP, R_HIP, L_ANKLE, R_ANKLE)


@dataclass
class BehaviourConfig:
    min_conf: float = 0.4               # keypoints below this confidence are ignored
    history_s: float = 12.0
    # possible distress (hands at the throat)
    throat_k: float = 0.45              # CUSUM allowance: one hand alone (score 0.4) never builds up
    throat_h: float = 0.8               # evidence-seconds: both hands for ~1.5 s
    throat_reach: float = 0.25          # a wrist within this many torso lengths of the throat point
    throat_refractory_s: float = 15.0
    # rhythmic movement
    rhythm_min_hz: float = 8.0          # resolving 1-5 Hz needs at least ~8 samples a second (Nyquist)
    rhythm_window_s: float = 6.0
    rhythm_min_span_s: float = 4.0
    rhythm_min_samples: int = 32
    rhythm_band: tuple = (1.0, 5.0)
    rhythm_peak_share: float = 0.6      # share of a limb's power at its peak (and first harmonic)
    rhythm_min_amplitude: float = 0.06  # RMS movement, torso lengths (the reference's 0.02 body lengths, body ~ 3 torsos)
    rhythm_min_limbs: int = 2
    rhythm_k: float = 0.3
    rhythm_h: float = 3.0
    rhythm_refractory_s: float = 30.0
    # stillness
    stillness_s: float = 30.0
    still_window_s: float = 2.0
    still_move: float = 0.12            # mean keypoint movement over the window, torso lengths (reference: 0.04 body lengths)
    min_points: int = 4
    max_gap_s: float = 1.5              # a person unseen this long is forgotten


@dataclass
class BehaviourEvent:
    kind: str                           # possible_distress | rhythmic_movement | stillness
    severity: str
    t: float
    box: np.ndarray
    detail: str


class Cusum:
    """S = max(0, S + (score - k)·dt), firing when S > h. dt is capped at 1 s, so a gap is not evidence."""

    def __init__(self, k: float, h: float, refractory: float):
        self.k, self.h, self.refractory = k, h, refractory
        self.s, self.last_t, self.fired_at = 0.0, None, -math.inf

    def update(self, score: float, t: float) -> bool:
        dt = 0.0 if self.last_t is None else min(max(t - self.last_t, 0.0), 1.0)
        self.last_t = t
        self.s = max(0.0, self.s + (score - self.k) * dt)
        if self.s <= self.h:
            return False
        if t - self.fired_at < self.refractory:
            self.s = self.h
            return False
        self.s, self.fired_at = 0.0, t
        return True


@dataclass
class _Track:
    box: np.ndarray
    last_t: float
    samples: deque = field(default_factory=deque)        # (t, {keypoint: (u, v) or None})
    torso: deque = field(default_factory=lambda: deque(maxlen=60))
    throat: Cusum | None = None
    rhythm: Cusum | None = None
    still_since: float | None = None
    still_fired: float = -math.inf

    def scale(self) -> float | None:
        return float(np.median(self.torso)) if self.torso else None


def _iou(a, b) -> float:
    x1, y1, x2, y2 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


class BehaviourDetector:
    def __init__(self, cfg: BehaviourConfig | None = None):
        self.cfg = cfg or BehaviourConfig()
        self.tracks: list[_Track] = []
        self.sample_rate = 0.0

    def _track_for(self, box, t) -> _Track:
        best, best_score = None, 0.2
        for tr in self.tracks:
            score = _iou(tr.box, box)
            if score > best_score:
                best, best_score = tr, score
        if best is None:
            c = self.cfg
            best = _Track(box, t, throat=Cusum(c.throat_k, c.throat_h, c.throat_refractory_s),
                          rhythm=Cusum(c.rhythm_k, c.rhythm_h, c.rhythm_refractory_s))
            self.tracks.append(best)
        best.box, best.last_t = box, t
        return best

    def update(self, people: list[Person], t: float, nap: bool = False) -> list[BehaviourEvent]:
        """One frame of people (pixels). nap=True switches the stillness check off (children asleep are still)."""
        c = self.cfg
        events: list[BehaviourEvent] = []
        seen = set()
        for p in people:
            tr = self._track_for(np.asarray(p.box, float), t)
            if id(tr) in seen:
                continue                                             # two boxes on one track: keep the first
            seen.add(id(tr))
            pts = {i: (float(p.kpts[i, 0]), float(p.kpts[i, 1])) if p.kpts[i, 2] >= c.min_conf else None for i in KEY}
            torso = self._torso(pts)
            if torso:
                tr.torso.append(torso)
            tr.samples.append((t, pts))
            while tr.samples and t - tr.samples[0][0] > c.history_s:
                tr.samples.popleft()
            self._update_rate(tr)
            L = tr.scale()
            if L is None or L < 5.0:
                continue                                             # no reliable size for this person yet
            for check in (self._throat, self._rhythm, self._stillness):
                ev = check(tr, pts, L, t, nap)
                if ev:
                    events.append(BehaviourEvent(ev[0], ev[1], t, np.asarray(p.box, float), ev[2]))
        self.tracks = [tr for tr in self.tracks if t - tr.last_t <= c.max_gap_s]
        return events

    @staticmethod
    def _mid(a, b):
        if a is None or b is None:
            return a if b is None else b
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    def _torso(self, pts) -> float | None:
        s, h = self._mid(pts[L_SHOULDER], pts[R_SHOULDER]), self._mid(pts[L_HIP], pts[R_HIP])
        if s is None or h is None or pts[L_SHOULDER] is None or pts[R_SHOULDER] is None:
            return None
        return math.hypot(h[0] - s[0], h[1] - s[1])

    def _update_rate(self, tr: _Track) -> None:
        times = [s[0] for s in list(tr.samples)[-20:]]
        gaps = np.diff(times)
        gaps = gaps[gaps > 0]
        if len(gaps):
            self.sample_rate = 1.0 / float(np.median(gaps))

    # ---- possible distress: both hands at the throat ----
    def _throat(self, tr, pts, L, t, nap):
        c, score = self.cfg, 0.0
        nose, ls, rs = pts[NOSE], pts[L_SHOULDER], pts[R_SHOULDER]
        if nose is not None and ls is not None and rs is not None:
            sh = self._mid(ls, rs)
            throat = (sh[0] + 0.35 * (nose[0] - sh[0]), sh[1] + 0.35 * (nose[1] - sh[1]))
            near = [w is not None and math.hypot(w[0] - throat[0], w[1] - throat[1]) < c.throat_reach * L for w in (pts[L_WRIST], pts[R_WRIST])]
            score = 1.0 if all(near) else 0.4 if any(near) else 0.0
        if tr.throat.update(score, t):
            return ("possible_distress", "high", "Both hands held at the throat for over a second (pose rule). Eating or touching the neck can look similar.")
        return None

    # ---- rhythmic movement ----
    def _rhythm(self, tr, pts, L, t, nap):
        c, score = self.cfg, 0.0
        window = [s for s in tr.samples if t - s[0] <= c.rhythm_window_s]
        if (self.sample_rate >= c.rhythm_min_hz and len(window) >= c.rhythm_min_samples
                and window[-1][0] - window[0][0] >= c.rhythm_min_span_s):
            if sum(self._limb_is_rhythmic(window, limb, L) for limb in LIMBS) >= c.rhythm_min_limbs:
                score = 1.0
        if tr.rhythm.update(score, t):
            return ("rhythmic_movement", "high", "Repeated 1-5 Hz movement in two or more limbs for several seconds (pose rule). Play or dancing can look similar.")
        return None

    def _limb_is_rhythmic(self, window, limb, L) -> bool:
        c = self.cfg
        present = [(s[0], s[1][limb]) for s in window if s[1][limb] is not None]
        if len(present) < 0.8 * len(window):
            return False
        ts = np.array([p[0] for p in present])
        xy = np.array([p[1] for p in present]) / L
        grid = np.arange(ts[0], ts[-1], 1.0 / self.sample_rate)
        if len(grid) < 8:
            return False
        freqs = np.fft.rfftfreq(len(grid), 1.0 / self.sample_rate)
        spectrum, power = np.zeros_like(freqs), 0.0
        for axis in (0, 1):
            sig = np.interp(grid, ts, xy[:, axis])
            sig = sig - np.polyval(np.polyfit(grid - grid[0], sig, 1), grid - grid[0])     # remove drift: walking is not shaking
            power += float(np.mean(sig ** 2))
            spectrum += np.abs(np.fft.rfft(sig * np.hanning(len(sig)))) ** 2
        usable = freqs > 0.2
        total = spectrum[usable].sum()
        if total <= 0 or math.sqrt(power) <= c.rhythm_min_amplitude:
            return False
        f0 = freqs[usable][np.argmax(spectrum[usable])]
        if not c.rhythm_band[0] <= f0 <= c.rhythm_band[1]:
            return False
        near = (np.abs(freqs - f0) <= 0.5) | (np.abs(freqs - 2 * f0) <= 0.5)
        return spectrum[near & usable].sum() / total > c.rhythm_peak_share

    # ---- stillness ----
    def _stillness(self, tr, pts, L, t, nap):
        c = self.cfg
        if nap:
            tr.still_since = None
            return None
        then = next((s for s in tr.samples if t - s[0] <= c.still_window_s), None)
        if then is None or t - then[0] < 0.75 * c.still_window_s:
            return None
        moves = [math.hypot(pts[i][0] - then[1][i][0], pts[i][1] - then[1][i][1]) / L
                 for i in KEY if pts[i] is not None and then[1][i] is not None]
        if len(moves) < c.min_points:
            tr.still_since = None
            return None
        if float(np.mean(moves)) < c.still_move:
            tr.still_since = tr.still_since if tr.still_since is not None else then[0]
        else:
            tr.still_since = None
        if tr.still_since is not None and t - tr.still_since >= c.stillness_s and t - tr.still_fired > c.stillness_s:
            tr.still_fired = t
            return ("stillness", "medium", f"Very little movement for {c.stillness_s:.0f} s outside nap time (pose rule). Breathing cannot be seen on video.")
        return None
