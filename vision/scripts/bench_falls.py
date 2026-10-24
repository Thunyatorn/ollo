"""Score fall detectors on the cached OmniFall/GMDCSA24 poses with the TEAM's scoring rule (hit = alert 0-5 s after onset).

    .venv/bin/python scripts/bench_falls.py [poses_s|poses_n] [--grid]
--grid searches the main thresholds on Subjects 1-3 ('tune') only, then reports the chosen setting on Subject 4 ('test').
"""
import gzip, itertools, json, pickle, sys
from dataclasses import replace
sys.path.insert(0, "."); sys.path.insert(0, "/Users/blackslex/Hackathons/ollo-remote")
from server.evaluate import score                      # the team's own scoring, for a fair comparison
from nestwatch_vision.detectors.fall import FallConfig, FallDetector
from nestwatch_vision.pose import Person

D = "/Users/blackslex/Hackathons/datasets/omnifall_gmdcsa24"
which = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "poses_s"
cache = pickle.load(gzip.open(f"{D}/{which}.pkl.gz"))
labels = json.load(open(f"{D}/labels.json"))["clips"]


def run(cfg, split=None, subject=None):
    clips = []
    for c in labels:
        if split and c["split"] != split:
            continue
        if subject and not c["omnifall_path"].startswith(subject + "/"):
            continue
        det, alerts, v = FallDetector(cfg), [], cache[c["omnifall_path"]]
        for t, ppl in v["frames"]:
            for e in det.update([Person(b, conf, k) for b, conf, k in ppl], t):
                alerts.append({"kind": "fall", "t_s": t})
        clips.append({"events": c["events"], "alerts": alerts, "duration_s": v["duration"]})
    r = score(clips).get("fall", {"tp": 0, "fn": sum(len(c["events"]) for c in clips), "fp": 0, "recall": 0, "precision": None})
    neg = [c for c in clips if not c["events"]]
    r["neg_clips_alarmed"] = sum(1 for c in neg if c["alerts"])
    r["n_neg"] = len(neg)
    return r


def line(name, r):
    p = "—" if r.get("precision") is None else f"{r['precision']:.0%}"
    return f"{name:28s} caught {r['tp']:2d}/{r['tp'] + r['fn']:2d} (recall {r['recall'] or 0:.0%})  false alarms {r['fp']:2d} (on {r['neg_clips_alarmed']}/{r['n_neg']} everyday clips)  precision {p}"


base = FallConfig()
if "--grid" not in sys.argv:
    for split, name in (("test", "TEST (Subject 4)"), ("tune", "TUNE (Subjects 1-3)"), (None, "ALL 160")):
        print(line(f"{which} {name}", run(base, split)))
    sys.exit()

grid = {"drop_frac": [0.25, 0.35, 0.45], "drop_window_s": [0.75, 1.0, 1.5], "low_height_frac": [0.45, 0.55, 0.65],
        "low_aspect": [0.9, 1.1], "hold_s": [0.5, 0.8, 1.2]}
f1 = lambda r: 2 * r["tp"] / max(2 * r["tp"] + r["fp"] + r["fn"], 1)            # balance misses and false alarms
robust = "--robust" in sys.argv
best = []
for vals in itertools.product(*grid.values()):
    cfg = replace(base, **dict(zip(grid, vals)))
    r = run(cfg, "tune")
    # --robust: judge a setting by its WORST tuning subject, so it is not rewarded for suiting one person (overfitting)
    key = min(f1(run(cfg, "tune", s)) for s in ("Subject_1", "Subject_2", "Subject_3")) if robust else f1(r)
    best.append((key, r["tp"], -r["fp"], vals, r))
best.sort(reverse=True)
print("top settings on TUNE (Subjects 1-3)" + (", ranked by the worst subject's F1:" if robust else ", ranked by F1:"))
for k, _, _, vals, r in best[:5]:
    print(f"  score {k:.2f}  {dict(zip(grid, vals))}\n     {line('', r)}")
chosen = replace(base, **dict(zip(grid, best[0][3])))
print("\nchosen on TUNE, reported on TEST (never seen):")
print(line(f"{which} TEST (Subject 4)", run(chosen, "test")))
print(line(f"{which} ALL 160", run(chosen)))
json.dump(dict(zip(grid, best[0][3])), open(f"{D}/fall_tuned_{which}{'_robust' if robust else ''}.json", "w"))
