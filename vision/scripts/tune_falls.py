"""Tune the fall rule on BOTH OmniFall datasets while keeping the test people unseen.

    .venv/bin/python scripts/tune_falls.py [--quick]

Tuning people (used to choose a setting):  GMDCSA24 Subjects 1-3;  CAUCAFall Subjects 1-7 and 10 (OmniFall train + val).
Test people (never used to choose):        GMDCSA24 Subject 4;     CAUCAFall Subjects 8 and 9  (OmniFall test).
A setting is judged by the F1 of its WORST tuning person, so it cannot win by suiting one person (MATH.md 8.1).
Scoring is the team's rule: an alert 0-5 s after the labelled fall is a catch, any other alert is a false alarm.
"""
import gzip, itertools, json, multiprocessing as mp, pickle, sys, time
from dataclasses import replace
sys.path.insert(0, ".")
from nestwatch_vision.detectors.fall import FallConfig, FallDetector
from nestwatch_vision.evaluation import wilson
from nestwatch_vision.pose import Person

ROOT = "/Users/blackslex/Hackathons/datasets"
HIT_S = 5.0
CLIPS = []          # (dataset, subject, group, onset, [(t, [Person])])


def load():
    for name in ("omnifall_gmdcsa24", "omnifall_caucafall"):
        cache = pickle.load(gzip.open(f"{ROOT}/{name}/poses_s.pkl.gz"))
        for c in json.load(open(f"{ROOT}/{name}/labels.json"))["clips"]:
            if name == "omnifall_gmdcsa24":
                subject, group = c["omnifall_path"].split("/")[0], ("test" if c["split"] == "test" else "tune")
            else:
                subject, group = f"S{c['subject']}", ("test" if c["omnifall_split"] == "test" else "tune")
            frames = [(t, [Person(b, conf, k) for b, conf, k in ppl]) for t, ppl in cache[c["omnifall_path"]]["frames"]]
            CLIPS.append((name[8:], subject, group, c["events"][0]["onset_s"] if c["events"] else None, frames))


def score(cfg, group):
    """{(dataset, subject): [caught, false alarms, missed]} for one setting."""
    out = {}
    for ds, subject, g, onset, frames in CLIPS:
        if g != group:
            continue
        det, alerts = FallDetector(cfg), []
        for t, people in frames:
            alerts += [t for _ in det.update(people, t)]
        r = out.setdefault((ds, subject), [0, 0, 0])
        hit = False
        for t in alerts:
            if onset is not None and 0 <= t - onset <= HIT_S and not hit:
                hit = True; r[0] += 1
            else:
                r[1] += 1
        if onset is not None and not hit:
            r[2] += 1
    return out


def f1(r):
    return 2 * r[0] / max(2 * r[0] + r[1] + r[2], 1)


def tune_one(args):
    cfg = replace(FallConfig(), **dict(args))
    per = score(cfg, "tune")
    tot = [sum(v[i] for v in per.values()) for i in range(3)]
    return (min(f1(v) for v in per.values()), f1(tot), args, tot)


def show(name, cfg, group):
    per = score(cfg, group)
    tot = [sum(v[i] for v in per.values()) for i in range(3)]
    falls = tot[0] + tot[2]
    lo, hi = wilson(tot[0], falls)
    print(f"  {name:28s} caught {tot[0]:3d}/{falls:3d} ({tot[0] / falls:.0%}, {lo:.0%}-{hi:.0%})   false alarms {tot[1]:2d}   F1 {f1(tot):.2f}")
    return tot


if __name__ == "__main__":
    quick = "--quick" in sys.argv
    load()
    base = FallConfig()
    grid = {"drop_frac": [0.35, 0.45, 0.55], "drop_window_s": [1.0, 1.5], "low_height_frac": [0.45, 0.55, 0.65],
            "low_aspect": [0.9, 1.1, 1.3], "lying_angle": [60.0, 75.0, 90.0, 200.0], "hold_s": [0.8, 1.2, 1.6]}
    if quick:
        grid = {k: v[:2] for k, v in grid.items()}
    combos = [tuple(zip(grid, vals)) for vals in itertools.product(*grid.values())]
    print(f"{len(CLIPS)} clips; {len(combos)} settings; tuning on {sum(1 for c in CLIPS if c[2] == 'tune')} clips")
    t0 = time.time()
    with mp.get_context("fork").Pool() as pool:
        results = pool.map(tune_one, combos, chunksize=4)
    results.sort(key=lambda r: (r[0], r[1]), reverse=True)
    print(f"searched in {time.time() - t0:.0f} s. Best by the worst tuning person's F1:")
    for worst, overall, args, tot in results[:5]:
        print(f"  worst-person F1 {worst:.2f}  overall F1 {overall:.2f}  caught {tot[0]} false {tot[1]} missed {tot[2]}  {dict(args)}")
    chosen = replace(base, **dict(results[0][2]))
    print("\nTUNING people:")
    show("current defaults", base, "tune")
    show("chosen setting", chosen, "tune")
    print("TEST people (never used to choose):")
    show("current defaults", base, "test")
    show("chosen setting", chosen, "test")
    json.dump(dict(results[0][2]), open(f"{ROOT}/fall_tuned_both.json", "w"))
    print(f"\nchosen setting saved to {ROOT}/fall_tuned_both.json")
