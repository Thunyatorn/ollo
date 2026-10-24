"""Turn OmniFall's GMDCSA24 labels into the labels.json the team's `server/evaluate.py` expects.

    python scripts/make_omnifall_labels.py DATASETS_DIR
where DATASETS_DIR holds   omnifall/labels/GMDCSA24.csv, omnifall/labels/label2id.csv, omnifall/splits/cs/gmdcsa24/*.csv
and                       gmdcsa24/Subject N/{ADL,Fall}/NN.mp4        (the videos, from the dataset's GitHub repo)
Each OmniFall 'fall' segment becomes an expected event {"kind": "fall", "onset_s": segment start}; a video with no
such segment is a negative. Videos in OmniFall's cross-subject TEST split are split="test", everything else "tune".
"""
import csv, json, sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
names = {int(r["id"]): r["label"] for r in csv.DictReader(open(root / "omnifall/labels/label2id.csv"))}
segments = defaultdict(list)
for r in csv.DictReader(open(root / "omnifall/labels/GMDCSA24.csv")):
    segments[r["path"]].append((names[int(r["label"])], float(r["start"]), float(r["end"])))
test = {r["path"] for r in csv.DictReader(open(root / "omnifall/splits/cs/gmdcsa24/test.csv"))}

clips, missing = [], []
for path, segs in sorted(segments.items()):
    video = Path("gmdcsa24") / (path.replace("Subject_", "Subject ") + ".mp4")          # 'Subject_1/Fall/01' -> 'Subject 1/Fall/01.mp4'
    if not (root / video).exists():
        missing.append(str(video))
        continue
    events = [{"kind": "fall", "onset_s": start} for label, start, _ in segs if label == "fall"]
    clips.append({"path": str(Path("..") / video), "split": "test" if path in test else "tune", "events": events,
                  "omnifall_path": path, "segments": [[l, s, e] for l, s, e in segs]})
out = root / "omnifall_gmdcsa24" / "labels.json"
out.parent.mkdir(exist_ok=True)
json.dump({"clips": clips}, open(out, "w"), indent=1)
pos = sum(1 for c in clips if c["events"])
print(f"{len(clips)} clips written to {out}: {pos} with a fall ({sum(len(c['events']) for c in clips)} fall events), {len(clips) - pos} negatives; "
      f"test split {sum(c['split'] == 'test' for c in clips)} clips, tune split {sum(c['split'] == 'tune' for c in clips)}")
if missing:
    print("MISSING videos:", missing[:5], "...", len(missing))
