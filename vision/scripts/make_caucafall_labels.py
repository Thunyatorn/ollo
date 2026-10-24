"""Turn OmniFall's CAUCAFall labels into a labels.json for eval_clips.py / bench_falls.py / the team's evaluate.py.

    python scripts/make_caucafall_labels.py DATASETS_DIR
where DATASETS_DIR holds  omnifall/labels/caucafall.csv, omnifall/labels/label2id.csv, omnifall/splits/cs/caucafall/*.csv
and                      caucafall/Dataset CAUCAFall/CAUCAFall/Subject.N/<activity>/<Name>S<N>.avi   (CC BY 4.0, Mendeley)
OmniFall paths look like 'backwards/FallBackwardsS1'; the file name is the key. Every clip is split="test": nothing
was tuned on CAUCAFall (our thresholds came from GMDCSA24), so all 100 are unseen. OmniFall's own cross-subject
split is kept as "omnifall_split".
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
names = {int(r["id"]): r["label"] for r in csv.DictReader(open(root / "omnifall/labels/label2id.csv"))}
segments = defaultdict(list)
for r in csv.DictReader(open(root / "omnifall/labels/caucafall.csv")):
    segments[r["path"]].append((names[int(r["label"])], float(r["start"]), float(r["end"]), int(r["subject"])))
split_of = {}
for part in ("train", "val", "test"):
    for r in csv.DictReader(open(root / f"omnifall/splits/cs/caucafall/{part}.csv")):
        split_of[r["path"]] = part
videos = {p.stem: p for p in (root / "caucafall").rglob("*.avi")}

clips, missing = [], []
for path, segs in sorted(segments.items()):
    video = videos.get(Path(path).name)
    if video is None:
        missing.append(path)
        continue
    events = [{"kind": "fall", "onset_s": start} for label, start, _, _ in sorted(segs, key=lambda s: s[1]) if label == "fall"]
    clips.append({"path": str(Path("..") / video.relative_to(root)), "split": "test", "omnifall_split": split_of.get(path),
                  "subject": segs[0][3], "events": events, "omnifall_path": path, "segments": [[l, s, e] for l, s, e, _ in segs]})
out = root / "omnifall_caucafall" / "labels.json"
out.parent.mkdir(exist_ok=True)
json.dump({"clips": clips}, open(out, "w"), indent=1)
pos = sum(1 for c in clips if c["events"])
print(f"{len(clips)} clips -> {out}: {pos} with a fall ({sum(len(c['events']) for c in clips)} fall events), {len(clips) - pos} without; "
      f"{len({c['subject'] for c in clips})} subjects")
if missing:
    print("MISSING videos:", missing[:5], len(missing))
