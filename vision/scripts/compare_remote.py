"""Run the teammates' ApproachMonitor (/Users/blackslex/Hackathons/ollo-remote/server/predict.py) and OUR pipeline on the same simulated children.

    .venv/bin/python scripts/compare_remote.py [N]
"""
import sys
import numpy as np
sys.path.insert(0, ".")
sys.path.insert(0, "/Users/blackslex/Hackathons/ollo-remote")
from server.predict import ApproachMonitor, Calibration
from nestwatch_vision.geometry import points_in_polygon
import scripts.sim_pipeline as ours
from scripts.scenarios import INFORMATIONAL, NON_THREATS, threat

STAIRS = np.array(ours.STAIRS, float)
FRAME = np.array([640.0, 480.0])
IMG = np.array([[100, 100], [500, 120], [560, 400], [60, 380], [300, 110], [310, 390]], float)    # same camera as our MATH 1.5 example
FLOOR = np.array([[0, 0], [4, 0], [4, 3], [0, 3], [2, 0], [2, 3]], float)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
FPS = 12.0                                                                                     # their stated frame rate


def hers(path, seed, sigma, duration=12.0):
    cal = Calibration.fit([{"image": (p / FRAME).tolist(), "floor": f.tolist()} for p, f in zip(IMG, FLOOR)])
    mon, rng = ApproachMonitor(seed=seed), np.random.default_rng(seed)
    fired = entered = None
    for k in range(int(duration * FPS)):
        t = k / FPS
        truth = np.asarray(path(t), float)
        if entered is None and points_in_polygon(truth, STAIRS):
            entered = t
        uv = cal.to_image(truth + rng.normal(0, sigma, 2))
        if uv is None:
            continue
        st = mon.update(1, uv, t, cal, STAIRS)
        if st["started"] and fired is None:
            fired = t
    return fired, entered


def mine(path, seed, sigma):
    ours.DT, ours.SM = 1 / FPS, sigma
    ours.R = np.eye(2) * sigma ** 2
    return ours.simulate(path, seed)


def report(name, run, sigma):
    res = [run(threat(s), s, sigma) for s in range(N)]
    ent = [(f, e) for f, e in res if e is not None]
    lead = [e - f for f, e in ent if f is not None and f < e]
    row = f"{name:6s} noise {sigma * 100:3.0f} cm | threats {len(ent):3d}: early {len(lead):3d} ({100 * len(lead) / max(len(ent), 1):3.0f}%)  warning median {np.median(lead) if lead else float('nan'):.2f}s  p10 {np.percentile(lead, 10) if lead else float('nan'):.2f}s | false alarms /{N}: "
    fa = []
    for label, fn in {**NON_THREATS, **INFORMATIONAL}.items():
        fa.append(f"{label.split()[0][:5]}{label.split()[-1][:6]}={sum(run(fn(s), s, sigma)[0] is not None for s in range(N))}")
    print(row + " ".join(fa))


for sigma in (0.03, 0.12):
    report("THEIRS", hers, sigma)
    report("OURS", mine, sigma)
