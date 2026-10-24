"""One camera frame's worth of people in, floor positions and alert events out. See MATH.md sections 1 to 7.

people (pixels) -> foot points -> floor meters (homography) -> tracker -> evidence per child and zone -> CUSUM -> events.
No camera, no network and no model in here, so every step can be tested with made-up people.
"""
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np

from .calibration import jacobian, to_floor
from .config import PipelineConfig, TrackerConfig
from .cusum import CusumBank
from .detectors.fall import FallConfig, FallDetector
from .detectors.not_visible import NotVisibleDetector
from .detectors.unsupervised import UnsupervisedConfig, evidence as supervision_evidence
from .pose import Person, foot_point
from .prediction import zone_evidence
from .tracker import Detection, Track, Tracker
from .zones import ZoneCache


@dataclass
class Event:
    track_id: str
    event_type: str                 # zone_entry_predicted | zone_entry | fall | unsupervised | child_not_visible
    zone_id: str
    severity: str
    predicted_entry_s: float | None
    clip_ref: str
    at: float


@dataclass
class StepResult:
    positions: list[dict] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    detections: int = 0
    skipped_out_of_room: int = 0


class Pipeline:
    def __init__(self, room_w: float, room_h: float, H: np.ndarray | None, zones: ZoneCache,
                 cfg: PipelineConfig | None = None, tracker_cfg: TrackerConfig | None = None, rng=None):
        self.room_w, self.room_h, self.H = room_w, room_h, H
        self.zones = zones
        self.cfg = cfg or PipelineConfig()
        self.tracker = Tracker(tracker_cfg)
        self.bank = CusumBank(self.cfg.cusum_k, self.cfg.cusum_h, self.cfg.cusum_cooldown_s)
        self.rng = rng or np.random.default_rng()
        self._foot_sigma = dict(self.cfg.foot_sigma_m)
        self.fall = FallDetector(FallConfig())
        self.sup_cfg = UnsupervisedConfig()
        self.sup_bank = CusumBank(self.sup_cfg.k, self.sup_cfg.h, self.sup_cfg.cooldown_s)
        self.not_visible = NotVisibleDetector()
        self._first_seen: dict[int, float] = {}
        self.adult_tagged = False               # the unsupervised check stays off until someone has been tagged as an adult

    def set_homography(self, H: np.ndarray | None) -> None:
        self.H = H

    def tag_adult(self, track_id: int, name: str) -> bool:
        """Mark a track as an adult (set from the dashboard). The tag follows the person if the track is lost and found again."""
        for tr in self.tracker.tracks:
            if tr.id == track_id:
                tr.tag = name
                self.adult_tagged = True
                return True
        return False

    # ---- one frame --------------------------------------------------------------------------------
    def step(self, people: list[Person], t: float, now: datetime, everyone: list[Person] | None = None) -> StepResult:
        """`people`: confident detections, for tracking. `everyone`: also the low-confidence ones, which the fall
        detector uses (a person lying on the floor often scores low)."""
        res = StepResult()
        if self.H is None:                                      # uncalibrated camera: we can see people but not place them
            return res

        dets = []
        for p in people:
            f = foot_point(p)
            xy = to_floor(self.H, (f.u, f.v))
            if not (-self.cfg.room_margin_m <= xy[0] <= self.room_w + self.cfg.room_margin_m and
                    -self.cfg.room_margin_m <= xy[1] <= self.room_h + self.cfg.room_margin_m):
                res.skipped_out_of_room += 1
                continue
            J = jacobian(self.H, (f.u, f.v))
            R = self.cfg.sigma_px ** 2 * J @ J.T + self._foot_sigma[f.quality] ** 2 * np.eye(2)     # MATH 1.8 and 3.3
            dets.append(Detection(xy, R, {"foot_quality": f.quality}))
        res.detections = len(dets)

        tracks = self.tracker.step(dets, t)
        res.tracks = tracks
        for tr in tracks:
            self._first_seen.setdefault(tr.id, t)
        for lost in self.tracker.newly_lost:
            self.bank.forget_track(lost.id)
            self.sup_bank.forget_track(lost.id)

        active = set(z.id for z in self.zones.active(now))
        for tr in tracks:
            adult = tr.tag is not None
            res.positions.append({
                "trackId": f"t{tr.id}", "kind": "adult" if adult else "child",
                "label": tr.tag[0].upper() if adult else str(tr.id),
                "x": round(float(tr.pos[0]), 3), "y": round(float(tr.pos[1]), 3),
                "vx": round(float(tr.vel[0]), 3), "vy": round(float(tr.vel[1]), 3), "visible": bool(tr.visible)})
            if adult or not tr.visible:
                continue
            for z in self.zones.zones:                          # every zone, so a zone switched off by its schedule empties its bucket
                armed = z.id in active
                ev = zone_evidence(tr.x, tr.P, z.polygon, self.cfg.horizon_s, self.cfg.evidence_samples, self.rng, self.cfg.shrink_c) if armed else None
                if self.bank.update((tr.id, z.id), ev.e if ev else 0.0, t, armed=armed):
                    res.events.append(Event(f"t{tr.id}", "zone_entry" if ev.inside else "zone_entry_predicted", z.id, z.severity,
                                            None if ev.entry_s is None else round(ev.entry_s, 2), f"evt_{int(t * 1000)}_t{tr.id}", t))

        # unsupervised child (MATH 8.4): only once adults are known
        if self.adult_tagged:
            adults = [tr.pos for tr in tracks if tr.tag is not None and tr.visible]
            for tr in tracks:
                if tr.tag is None and tr.visible:
                    e = supervision_evidence(tr.pos, adults, self.sup_cfg)
                    if self.sup_bank.update((tr.id, "unsupervised"), e, t):
                        res.events.append(Event(f"t{tr.id}", "unsupervised", "", "medium", None, f"evt_{int(t * 1000)}_t{tr.id}", t))

        # a child the camera lost (CLUADE.md failure table): a low alert, after the checks in detectors/not_visible.py
        ages = {tid: t - t0 for tid, t0 in self._first_seen.items()}
        children = [tr.pos for tr in tracks if tr.tag is None and tr.visible]
        for lost in self.not_visible.update(self.tracker.newly_lost, self.tracker.lost, children, ages, t):
            res.events.append(Event(f"t{lost.id}", "child_not_visible", "", "low", None, f"evt_{int(t * 1000)}_t{lost.id}", t))
        live = {tr.id for tr in self.tracker.tracks} | {l.id for l in self.tracker.lost}
        self._first_seen = {k: v for k, v in self._first_seen.items() if k in live}

        # falls (MATH 8.1): detected in the picture, attached to the nearest tracked person on the floor
        for f in self.fall.update(everyone if everyone is not None else people, t):
            x1, _, x2, y2 = (float(v) for v in f.box)
            xy = to_floor(self.H, ((x1 + x2) / 2, y2))
            near = min(tracks, key=lambda tr: float(np.hypot(*(tr.pos - xy))), default=None)
            if near is not None and float(np.hypot(*(near.pos - xy))) > 1.5:
                near = None
            if near is not None and near.tag is not None:
                continue                                        # a tagged caregiver kneeling or lying down is not a child's fall
            tid = near.id if near is not None else 0
            res.events.append(Event(f"t{tid}", "fall", "", "high", None, f"evt_{int(t * 1000)}_t{tid}", t))
        return res
