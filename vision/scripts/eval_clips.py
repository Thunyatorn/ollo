"""M9: run the WHOLE vision pipeline offline on labelled clips, score every event kind, optionally tune on a split.

    .venv/bin/python scripts/eval_clips.py LABELS_JSON [--split test] [--poses CACHE.pkl.gz] [--demo-map] [--room 4x3]
    .venv/bin/python scripts/eval_clips.py LABELS_JSON --tune "cusum_h=0.15,0.2,0.3 fall.hold_s=0.5,0.8,1.2"

labels.json (same format as the team's evaluator, plus optional per-clip room set-up):
  {"clips": [{"path": "clips/a.mp4", "split": "tune" | "test",
              "events": [{"kind": "zone_entry" | "zone_entry_predicted" | "fall" | "unsupervised", "onset_s": 3.2}],
              "calibration": {"image_points": [[u, v], ...], "floor_points": [[x, y], ...]},      # optional
              "zones": [{"id": "z_1", "name": "Stairs", "severity": "high", "status": "active",
                         "polygon": [{"x": 2.8, "y": 1.9}, ...]}],                                  # optional
              "adults": [[track_id_at_seconds, "Maria"]]}]}                                         # optional
Without a calibration, --demo-map stretches the picture over the room (positions are not real; falls still work).
"""
import argparse, gzip, json, pickle, sys
from datetime import datetime
from itertools import product
from pathlib import Path
import cv2
import numpy as np
sys.path.insert(0, ".")
from nestwatch_vision.calibration import calibrate, demo_homography
from nestwatch_vision.config import PipelineConfig, PoseConfig
from nestwatch_vision.detectors.fall import FallConfig
from nestwatch_vision.evaluation import score
from nestwatch_vision.pipeline import Pipeline
from nestwatch_vision.pose import Person
from nestwatch_vision.zones import ZoneCache

NOON = datetime(2026, 1, 1, 12, 0)


def frames_of(clip, root, poses, model):
    if poses is not None:
        v = poses[clip.get("omnifall_path", clip["path"])]
        return v["size"], v["duration"], [(t, [Person(b, c, k) for b, c, k in ppl]) for t, ppl in v["frames"]]
    cap = cv2.VideoCapture(str((root / clip["path"]).resolve()))
    fps, out, idx, nxt, size = cap.get(cv2.CAP_PROP_FPS) or 30.0, [], 0, 0.0, None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = idx / fps; idx += 1
        if t + 1e-6 < nxt:
            continue
        nxt += 1 / 12.0
        size = (f.shape[1], f.shape[0])
        out.append((t, model.infer_all(f)))
    return size, idx / fps, out


def run_clip(clip, frames, size, duration, args, overrides):
    room_w, room_h = args.room
    if "calibration" in clip:
        H = calibrate(np.array(clip["calibration"]["image_points"], float), np.array(clip["calibration"]["floor_points"], float)).H
    elif args.demo_map:
        H = demo_homography(size[0], size[1], room_w, room_h)
    else:
        raise SystemExit(f"{clip['path']}: no calibration (add one, or pass --demo-map)")
    zones = ZoneCache(); zones.load(clip.get("zones", []))
    pcfg = PipelineConfig(**{k: v for k, v in overrides.items() if "." not in k})
    p = Pipeline(room_w, room_h, H, zones, pcfg, rng=np.random.default_rng(0))
    p.fall.cfg = FallConfig(**{**FallConfig().__dict__, **{k[5:]: v for k, v in overrides.items() if k.startswith("fall.")}})
    adults = {round(float(t), 1): name for t, name in clip.get("adults", [])}
    alerts = []
    for t, ppl in frames:
        tracked = [q for q in ppl if q.box_conf >= 0.25]
        res = p.step(tracked, t, NOW_FOR(clip), ppl)
        for at, name in list(adults.items()):                      # tag whoever is nearest the given time's first track
            if t >= at and res.tracks:
                p.tag_adult(res.tracks[0].id, name); adults.pop(at)
        alerts += [{"kind": e.event_type, "t_s": round(t, 3)} for e in res.events]
    return {"events": clip.get("events", []), "alerts": alerts, "duration_s": duration}


NOW_FOR = lambda clip: NOON


def evaluate(clips, cache, args, overrides):
    return score([run_clip(c, cache[i][2], cache[i][0], cache[i][1], args, overrides) for i, c in enumerate(clips)])


def show(title, rep):
    print(title)
    for kind, r in rep.items():
        rec = "—" if r["recall"] is None else f"{r['recall']:.0%} ({r['recall_ci'][0]:.0%}–{r['recall_ci'][1]:.0%})"
        prec = "—" if r["precision"] is None else f"{r['precision']:.0%}"
        fah = "—" if r["false_alarms_per_hour"] is None else f"{r['false_alarms_per_hour']:.1f}"
        dl = "—" if r["mean_delay_s"] is None else f"{r['mean_delay_s']:.1f}s"
        print(f"   {kind:22s} hits {r['tp']:3d}  missed {r['fn']:3d}  false alarms {r['fp']:3d} | recall {rec}  precision {prec}  delay {dl}  FA/hour {fah}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels"); ap.add_argument("--split"); ap.add_argument("--poses"); ap.add_argument("--demo-map", action="store_true")
    ap.add_argument("--room", default="4x3", type=lambda s: tuple(float(v) for v in s.split("x")))
    ap.add_argument("--weights", default=PoseConfig().weights); ap.add_argument("--tune")
    args = ap.parse_args()
    labels = Path(args.labels)
    clips = json.load(open(labels))["clips"]
    poses = pickle.load(gzip.open(args.poses)) if args.poses else None
    model = None
    if poses is None:
        from nestwatch_vision.pose import PoseModel
        model = PoseModel(PoseConfig(weights=args.weights))
    cache = [frames_of(c, labels.parent, poses, model) for c in clips]            # pose once; tuning only re-runs the rules
    sel = lambda s: [i for i, c in enumerate(clips) if s is None or c.get("split", "test") == s]
    if not args.tune:
        idx = sel(args.split)
        show(f"{len(idx)} clips{' (' + args.split + ')' if args.split else ''}:", evaluate([clips[i] for i in idx], [cache[i] for i in idx], args, {}))
        return
    space = {kv.split("=")[0]: [float(x) for x in kv.split("=")[1].split(",")] for kv in args.tune.split()}
    tune, test = sel("tune"), sel("test")
    best = None
    for vals in product(*space.values()):
        ov = dict(zip(space, vals))
        rep = evaluate([clips[i] for i in tune], [cache[i] for i in tune], args, ov)
        tp = sum(r["tp"] for r in rep.values()); fp = sum(r["fp"] for r in rep.values()); fn = sum(r["fn"] for r in rep.values())
        f1 = 2 * tp / max(2 * tp + fp + fn, 1)
        if best is None or f1 > best[0]:
            best = (f1, ov)
    print(f"best on TUNE (F1 {best[0]:.2f}): {best[1]}")
    show("on TEST with that setting:", evaluate([clips[i] for i in test], [cache[i] for i in test], args, best[1]))


if __name__ == "__main__":
    main()
