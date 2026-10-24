"""Run simulated children through tracker -> evidence -> CUSUM and report alert timing. Shared by the integration test."""
import numpy as np
from nestwatch_vision.cusum import CusumBank
from nestwatch_vision.geometry import points_in_polygon
from nestwatch_vision.prediction import zone_evidence
from nestwatch_vision.tracker import Detection, Tracker

STAIRS = [(2.8, 1.9), (4, 1.9), (4, 3), (2.8, 3)]
DT, SM = 1 / 8, 0.12
R = np.eye(2) * SM ** 2


def simulate(path, seed, duration=12.0, zone=STAIRS, tracker_cfg=None, k=0.3, h=0.2, shrink_c=0.5, horizon=3.0):
    """path: t -> (x, y) of the true child. Returns (alert_time or None, true_entry_time or None)."""
    rng = np.random.default_rng(seed)
    tracker, bank = Tracker(tracker_cfg), CusumBank(k=k, h=h)
    fired, entered = None, None
    for k in range(int(duration / DT)):
        t = k * DT
        truth = np.asarray(path(t), float)
        if entered is None and points_in_polygon(truth, zone):
            entered = t
        for tr in tracker.step([Detection(truth + rng.normal(0, SM, 2), R)], t):
            if not tr.visible:
                continue
            ev = zone_evidence(tr.x, tr.P, zone, horizon=horizon, rng=rng, shrink_c=shrink_c)
            if bank.update((tr.id, "stairs"), ev.e, t) and fired is None:
                fired = t
    return fired, entered
