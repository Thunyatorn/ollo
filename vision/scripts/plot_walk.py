"""Plot one scripted walk at the stairs: where the child is, the evidence, and the CUSUM bucket. Writes walk.png."""
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, ".")
from nestwatch_vision.cusum import CusumBank
from nestwatch_vision.geometry import points_in_polygon
from nestwatch_vision.prediction import zone_evidence
from nestwatch_vision.tracker import Detection, Tracker
from scripts.sim_pipeline import STAIRS, DT, R, SM

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 3
rng = np.random.default_rng(seed)
x0, y, speed, wait = 0.6, 2.4, 0.5, 1.0                    # stands for a second, then walks at the stairs at 0.5 m/s
path = lambda t: np.array([x0 + speed * max(0, t - wait), y])
tracker, bank = Tracker(), CusumBank()
T, E, S, X, SIGV, fire, entry = [], [], [], [], [], None, None
for k in range(int(8 / DT)):
    t = k * DT
    truth = path(t)
    if entry is None and points_in_polygon(truth, STAIRS):
        entry = t
    for tr in tracker.step([Detection(truth + rng.normal(0, SM, 2), R)], t):
        ev = zone_evidence(tr.x, tr.P, STAIRS, rng=rng)
        if bank.update((tr.id, "s"), ev.e, t) and fire is None:
            fire = t
        T.append(t); E.append(ev.e); S.append(bank.level((tr.id, "s"))); X.append(truth[0]); SIGV.append(tr.speed)

fig, ax = plt.subplots(3, 1, figsize=(8, 7), sharex=True)
ax[0].plot(T, X, "k"); ax[0].axhline(2.8, color="#b00000", ls="--"); ax[0].set_ylabel("child x (m)"); ax[0].text(0.1, 2.85, "stairs edge", color="#b00000")
ax[1].plot(T, E, "#1f3f8f"); ax[1].plot(T, np.minimum(SIGV, 1.5) / 1.5, color="#999", lw=1, label="estimated speed (scaled)"); ax[1].axhline(0.3, color="#a65a00", ls=":", label="leak k = 0.3")
ax[1].set_ylabel("evidence e"); ax[1].legend(loc="upper left", fontsize=8)
ax[2].plot(T, S, "#006400"); ax[2].axhline(0.2, color="#b00000", ls="--", label="alert threshold h = 0.2"); ax[2].set_ylabel("CUSUM bucket S"); ax[2].set_xlabel("time (s)"); ax[2].legend(loc="upper left", fontsize=8)
for a in ax:
    if fire is not None: a.axvline(fire, color="#b00000", lw=1)
    if entry is not None: a.axvline(entry, color="k", lw=1, ls="-.")
ax[0].set_title(f"Walk at the stairs (seed {seed}): alert {fire:.2f}s (red), entry {entry:.2f}s (dash-dot), warning {entry - fire:.2f}s", fontsize=10)
fig.tight_layout(); fig.savefig("walk.png", dpi=110)
print(f"alert at {fire:.2f} s, child enters at {entry:.2f} s, warning {entry - fire:.2f} s")
