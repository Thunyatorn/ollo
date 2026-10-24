"""Run the pose model once over every OmniFall/GMDCSA24 clip and save the detections, so fall rules can be tried in seconds.

    .venv/bin/python scripts/cache_poses.py LABELS_JSON WEIGHTS OUT.pkl.gz
Frames are prepared exactly like the team's evaluator (12 fps, 640 px wide, JPEG quality 65), so results are comparable.
"""
import gzip, json, pickle, sys, time
from pathlib import Path
import cv2
import numpy as np
sys.path.insert(0, ".")
from nestwatch_vision.config import PoseConfig
from nestwatch_vision.pose import PoseModel

labels, weights, out = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
model = PoseModel(PoseConfig(weights=weights))
clips = json.load(open(labels))["clips"]
cache, t0 = {}, time.time()
for i, c in enumerate(clips):
    cap = cv2.VideoCapture(str((labels.parent / c["path"]).resolve()))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frames, idx, nxt, size = [], 0, 0.0, None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = idx / fps; idx += 1
        if t + 1e-6 < nxt:
            continue
        nxt += 1 / 12.0
        f = cv2.resize(f, (640, round(640 * f.shape[0] / f.shape[1])))
        f = cv2.imdecode(cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 65])[1], cv2.IMREAD_COLOR)
        size = (f.shape[1], f.shape[0])
        frames.append((t, [(p.box.astype(np.float32), p.box_conf, p.kpts.astype(np.float32)) for p in model.infer_all(f)]))
    cap.release()
    cache[c["omnifall_path"]] = {"size": size, "duration": idx / fps, "frames": frames}
    if i % 40 == 0:
        print(f"{i}/{len(clips)} clips, {time.time() - t0:.0f}s", flush=True)
pickle.dump(cache, gzip.open(out, "wb"))
print(f"done: {len(cache)} clips, {sum(len(v['frames']) for v in cache.values())} frames in {time.time() - t0:.0f}s -> {out}")
