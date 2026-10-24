"""Score the team's detector on OmniFall/GMDCSA24 using ITS OWN scoring function, per split, and list the misses.

    /path/to/ollo-remote/.venv/bin/python scripts/score_omnifall.py EVAL_JSON
Run with the team repo's Python so `server.evaluate` imports (it is only used for score() and wilson()).
"""
import collections, json, sys
sys.path.insert(0, "/Users/blackslex/Hackathons/ollo-remote")
from server.evaluate import HIT_WINDOW_S, score

clips = json.load(open(sys.argv[1]))["clips"]
fmt = lambda v, ci: "—" if v is None else f"{v:.0%} ({ci[0]:.0%}–{ci[1]:.0%})"


def show(name, cs):
    rep = score(cs)
    pos = [c for c in cs if c["events"]]
    neg = [c for c in cs if not c["events"]]
    neg_h = sum(c["duration_s"] for c in neg) / 3600
    f = rep.get("fall", {"tp": 0, "fn": 0, "fp": 0, "precision": None, "recall": None, "precision_ci": (0, 0), "recall_ci": (0, 0), "mean_delay_s": None})
    print(f"{name}: {len(cs)} clips ({len(pos)} with a fall, {len(neg)} without, {neg_h * 60:.1f} min of negative footage)")
    print(f"   FALL   hits {f['tp']}  missed {f['fn']}  false alarms {f['fp']}  |  recall {fmt(f['recall'], f['recall_ci'])}  precision {fmt(f['precision'], f['precision_ci'])}  mean delay {f['mean_delay_s'] or 0:.1f}s")
    neg_fall_fp = sum(1 for c in neg for a in c["alerts"] if a["kind"] == "fall")
    print(f"          falsely alarmed in {sum(1 for c in neg if any(a['kind'] == 'fall' for a in c['alerts']))} of {len(neg)} clips without a fall ({neg_fall_fp} alerts)")
    others = collections.Counter(a["kind"] for c in cs for a in c["alerts"] if a["kind"] != "fall")
    if others:
        print("   other alert kinds raised (no labels exist for them here):", dict(others))
    return pos


pos_all = []
for name, sel in (("OFFICIAL TEST SPLIT (Subject 4, never used for tuning)", lambda c: c["split"] == "test"),
                  ("SUBJECTS 1-3", lambda c: c["split"] == "tune"), ("ALL 160 CLIPS", lambda c: True)):
    pos_all = show(name, [c for c in clips if sel(c)])
    print()

print(f"Missed falls (no 'fall' alert within 0-{HIT_WINDOW_S:g}s after onset), all clips:")
late = early = silent = 0
for c in clips:
    for e in c["events"]:
        times = sorted(a["t_s"] for a in c["alerts"] if a["kind"] == "fall")
        hit = [t for t in times if e["onset_s"] <= t <= e["onset_s"] + HIT_WINDOW_S]
        if hit:
            continue
        before = [t for t in times if t < e["onset_s"]]
        after = [t for t in times if t > e["onset_s"] + HIT_WINDOW_S]
        if not times:
            silent += 1
        elif before and not after:
            early += 1
        else:
            late += 1
print(f"   never alerted: {silent}   alerted only BEFORE the labelled onset: {early}   alerted but later than {HIT_WINDOW_S:g}s: {late}")
delays = [min(t - e["onset_s"] for t in (a["t_s"] for a in c["alerts"] if a["kind"] == "fall") if t >= e["onset_s"]) for c in clips for e in c["events"]
          if any(a["kind"] == "fall" and a["t_s"] >= e["onset_s"] for a in c["alerts"])]
if delays:
    delays.sort(); n = len(delays)
    print(f"   delay from onset to the first fall alert at or after it (n={n}): median {delays[n // 2]:.1f}s, 25% {delays[n // 4]:.1f}s, 75% {delays[3 * n // 4]:.1f}s, max {delays[-1]:.1f}s")
