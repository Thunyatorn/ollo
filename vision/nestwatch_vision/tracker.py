"""Multi-person tracking: Kalman filter per person, Hungarian matching between frames. See MATH.md sections 3 and 4."""
from dataclasses import dataclass, field
import numpy as np
from scipy.optimize import linear_sum_assignment

from . import kalman
from .config import TrackerConfig

BIG = 1e6


@dataclass
class Detection:
    pos: np.ndarray                 # floor position (x, y), meters
    R: np.ndarray                   # 2x2 measurement noise (m^2); derive from the Jacobian and foot quality (MATH 1.8, 3.3)
    meta: dict = field(default_factory=dict)   # anything the caller wants carried along (keypoints, camera id, ...)


@dataclass
class Track:
    id: int
    x: np.ndarray
    P: np.ndarray
    t: float                        # time of the current state
    born_pos: np.ndarray
    status: str = "tentative"       # tentative | confirmed
    hits: list = field(default_factory=list)   # last few frames: True = matched
    last_update_t: float = 0.0
    last_seen_pos: np.ndarray | None = None   # where the camera last actually saw them
    visible: bool = True            # matched in the most recent step
    tag: str | None = None          # e.g. adult caregiver name, set from the dashboard
    meta: dict = field(default_factory=dict)

    @property
    def pos(self) -> np.ndarray:
        return self.x[:2]

    @property
    def vel(self) -> np.ndarray:
        return self.x[2:]

    @property
    def speed(self) -> float:
        return float(np.linalg.norm(self.x[2:]))


@dataclass
class LostTrack:
    id: int
    pos: np.ndarray
    tag: str | None
    lost_at: float


class Tracker:
    def __init__(self, cfg: TrackerConfig | None = None):
        self.cfg = cfg or TrackerConfig()
        self.tracks: list[Track] = []
        self.lost: list[LostTrack] = []
        self.newly_lost: list[LostTrack] = []     # filled each step: tracks that just timed out
        self._next_id = 1

    # ---- main entry point -------------------------------------------------------------------
    def step(self, detections: list[Detection], t: float) -> list[Track]:
        """Advance to time t with this frame's detections. Returns the confirmed tracks."""
        cfg = self.cfg
        self.newly_lost = []

        for tr in self.tracks:                                   # predict
            dt = max(t - tr.t, 1e-3)
            tr.x, tr.P = kalman.predict(tr.x, tr.P, dt, cfg.sigma_a)
            tr.t = t

        matches, unmatched_tracks, unmatched_dets = self._associate(detections)

        for ti, di in matches:                                   # update
            tr, det = self.tracks[ti], detections[di]
            tr.x, tr.P, _ = kalman.update(tr.x, tr.P, det.pos, det.R)
            self._cap_speed(tr)
            tr.last_update_t, tr.visible, tr.meta, tr.last_seen_pos = t, True, det.meta, det.pos.copy()
            self._record(tr, True)

        survivors: list[Track] = []
        matched_ids = {ti for ti, _ in matches}
        for ti, tr in enumerate(self.tracks):
            if ti not in matched_ids:
                tr.visible = False
                self._record(tr, False)
                if tr.status == "tentative":                      # one miss kills a tentative track (ghost filter)
                    continue
                if t - tr.last_update_t > cfg.lost_timeout:      # confirmed, unseen too long
                    lost = LostTrack(tr.id, tr.last_seen_pos.copy(), tr.tag, t)
                    self.lost.append(lost)
                    self.newly_lost.append(lost)
                    continue
            survivors.append(tr)
        self.tracks = survivors

        for di in unmatched_dets:                                # births
            det = detections[di]
            P0 = np.diag([det.R[0, 0], det.R[1, 1], cfg.init_vel_sigma ** 2, cfg.init_vel_sigma ** 2])
            self.tracks.append(Track(self._next_id, np.array([*det.pos, 0.0, 0.0]), P0, t, det.pos.copy(),
                                     hits=[True], last_update_t=t, last_seen_pos=det.pos.copy(), meta=det.meta))
            self._next_id += 1

        for tr in self.tracks:                                   # promotion and re-identification
            if tr.status == "tentative" and sum(tr.hits[-cfg.confirm_window:]) >= cfg.confirm_hits:
                tr.status = "confirmed"
                self._reidentify(tr, t)
        self.lost = [l for l in self.lost if t - l.lost_at <= cfg.reid_window]
        return [tr for tr in self.tracks if tr.status == "confirmed"]

    # ---- helpers ------------------------------------------------------------------------------
    def _associate(self, detections: list[Detection]):
        n, m = len(self.tracks), len(detections)
        if n == 0 or m == 0:
            return [], list(range(n)), list(range(m))
        cost = np.full((n, m), BIG)
        for i, tr in enumerate(self.tracks):
            for j, det in enumerate(detections):
                d2 = kalman.mahalanobis2(tr.x, tr.P, det.pos, det.R)
                if d2 <= self.cfg.gate:                           # statistical gate (MATH 4.3)
                    cost[i, j] = d2
        rows, cols = linear_sum_assignment(cost)                  # globally best one-to-one assignment
        matches = [(i, j) for i, j in zip(rows, cols) if cost[i, j] < BIG]
        um_t = sorted(set(range(n)) - {i for i, _ in matches})
        um_d = sorted(set(range(m)) - {j for _, j in matches})
        return matches, um_t, um_d

    def _record(self, tr: Track, hit: bool):
        tr.hits.append(hit)
        del tr.hits[:-self.cfg.confirm_window]

    def _cap_speed(self, tr: Track):
        if tr.speed > self.cfg.speed_cap:                         # a bad match, not a sprint (MATH 3.6)
            tr.x[2:] *= self.cfg.speed_cap / tr.speed

    def _reidentify(self, tr: Track, t: float):
        """A newly confirmed track born near a recently lost one is the same person (MATH 4.5)."""
        best, best_d = None, self.cfg.reid_distance
        for l in self.lost:
            d = float(np.linalg.norm(tr.born_pos - l.pos))
            if t - l.lost_at <= self.cfg.reid_window and d <= best_d:
                best, best_d = l, d
        if best is not None:
            tr.id, tr.tag = best.id, best.tag
            self.lost.remove(best)
