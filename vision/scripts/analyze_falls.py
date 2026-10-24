"""What do real falls and false alarms look like to the fall rule? Runs the detector over cached poses of both datasets and
prints, per outcome, the body measurements at the alert (and the nearest thing to an alert for missed falls).

    .venv/bin/python scripts/analyze_falls.py
Uses poses_s.pkl.gz of omnifall_gmdcsa24 and omnifall_caucafall (made by cache_poses.py).
"""
import gzip, json, pickle, sys
from collections import defaultdict
sys.path.insert(0, ".")
from nestwatch_vision.detectors.fall import FallConfig, FallDetector
from nestwatch_vision.pose import Person

ROOT = "/Users/blackslex/Hackathons/datasets"
HIT = 5.0


def run(cfg, name):
    cache = pickle.load(gzip.open(f"{ROOT}/{name}/poses_s.pkl.gz"))
    out = []
    for c in json.load(open(f"{ROOT}/{name}/labels.json"))["clips"]:
        det, alerts = FallDetector(cfg), []
        for t, ppl in cache[c["omnifall_path"]]["frames"]:
            alerts += [(t, e.info) for e in det.update([Person(b, conf, k) for b, conf, k in ppl], t)]
        onset = c["events"][0]["onset_s"] if c["events"] else None
        kind = c["path"].split("/")[-2] if name == "omnifall_caucafall" else ("Fall" if onset is not None else "ADL")
        out.append({"clip": c["omnifall_path"], "kind": kind, "onset": onset, "alerts": alerts, "dataset": name,
                    "subject": c.get("subject") or c["omnifall_path"].split("/")[0]})
    return out


def f(v):
    return "  -  " if v is None else f"{v:5.2f}"


if __name__ == "__main__":
    rows = run(FallConfig(), "omnifall_gmdcsa24") + run(FallConfig(), "omnifall_caucafall")
    groups = defaultdict(list)
    for r in rows:
        hit = None
        for t, info in r["alerts"]:
            if r["onset"] is not None and 0 <= t - r["onset"] <= HIT and hit is None:
                hit = (t, info)
                groups["TRUE alert"].append((r, t, info))
            else:
                groups["FALSE alert"].append((r, t, info))
        if r["onset"] is not None and hit is None:
            groups["MISSED fall"].append((r, None, None))
    for g, items in groups.items():
        print(f"\n== {g}: {len(items)}")
        if g == "MISSED fall":
            by = defaultdict(int)
            for r, _, _ in items:
                by[(r["dataset"][8:], r["kind"])] += 1
            print("   ", dict(by))
            continue
        by = defaultdict(list)
        for r, t, info in items:
            by[(r["dataset"][8:], r["kind"])].append(info)
        for k, infos in sorted(by.items()):
            n = len(infos)
            avg = lambda key: (sum(i[key] for i in infos if i[key] is not None) / max(1, sum(1 for i in infos if i[key] is not None)))
            print(f"   {k[0]:9s} {k[1]:15s} n={n:2d}  h_ratio {f(avg('h_ratio'))}  aspect {f(avg('aspect'))}  torso angle {avg('angle'):5.1f}  low for {f(avg('since_low'))}s")
