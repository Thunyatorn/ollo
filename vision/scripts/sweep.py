"""python scripts/sweep.py SIGMA_A K H SHRINK_C HORIZON [N]  ->  one line of results for that setting."""
import sys, time
import numpy as np
sys.path.insert(0, ".")
from nestwatch_vision.config import TrackerConfig
from scripts.sim_pipeline import simulate
from scripts.scenarios import threat, NON_THREATS, INFORMATIONAL

sa, k, h, c, hz = (float(v) for v in sys.argv[1:6])
n = int(sys.argv[6]) if len(sys.argv) > 6 else 60
cfg = TrackerConfig(sigma_a=sa)
t0 = time.time()
res = [simulate(threat(s), s, tracker_cfg=cfg, k=k, h=h, shrink_c=c, horizon=hz) for s in range(n)]
enters = [(f, e) for f, e in res if e is not None]
ok = [e - f for f, e in enters if f is not None and f < e]
missed = len(enters) - len(ok)
fa = {name: sum(1 for s in range(n) if simulate(fn(s), s, tracker_cfg=cfg, k=k, h=h, shrink_c=c, horizon=hz)[0] is not None) for name, fn in {**NON_THREATS, **INFORMATIONAL}.items()}
print(f"sigma_a={sa} k={k} h={h} c={c} horizon={hz} | threats that entered: {len(enters)}  alerted early: {len(ok)}  missed/late: {missed} | "
      f"lead s p10 {np.percentile(ok,10):.2f} median {np.median(ok):.2f} | false alarms /{n}: "
      + " ".join(f"{name.split()[0][:5]}{name.split()[1][:5] if len(name.split())>1 else ''}={v}" for name, v in fa.items()) + f"   [{time.time()-t0:.0f}s]")
