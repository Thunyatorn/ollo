"""Why does the team's fall rule miss? Peek inside their engine around each labelled fall.

    /path/to/ollo-remote/.venv/bin/python scripts/diagnose_falls.py LABELS_JSON EVAL_JSON OUT_JSON
For every clip with a labelled fall, run their engine as their evaluator does and record, in the window from the labelled
onset to 5 s later: was anyone tracked, did their rule ever call the person 'lying', did it see the rapid drop.
"""
import asyncio, base64, json, math, sys
from pathlib import Path
import cv2
sys.path.insert(0, "/Users/blackslex/Hackathons/ollo-remote")
from server.vision import VisionEngine

labels = Path(sys.argv[1])
clips = [c for c in json.load(open(labels))["clips"] if c["events"]]
alerted = {c["name"]: c for c in json.load(open(sys.argv[2]))["clips"]}


async def run(engine, clip):
    cap = cv2.VideoCapture(str((labels.parent / clip["path"]).resolve()))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    onset = clip["events"][0]["onset_s"]
    engine.configure({})
    rows, idx, nxt, seq = [], 0, 0.0, 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        t = idx / fps; idx += 1
        if t + 1e-6 < nxt:
            continue
        nxt += 1 / 12.0
        f = cv2.resize(f, (640, round(640 * f.shape[0] / f.shape[1])))
        jpeg = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 65])[1].tobytes()
        res = await engine.process_frame({"session_id": "d", "epoch": 1, "frame_seq": seq, "media_time_ms": t * 1000, "image": base64.b64encode(jpeg).decode()})
        seq += 1
        tracks = engine.events.tracks
        rows.append({"t": t, "people": len(res.get("overlays", [])),
                     "lying": any(tr.lying_since is not None for tr in tracks.values()),
                     "drop": any(tr.drop_at > -math.inf and t - tr.drop_at <= 3.0 for tr in tracks.values()),
                     "collapse": any(tr.collapse_at > -math.inf and t - tr.collapse_at <= 3.0 for tr in tracks.values()),
                     "low": any(tr.low_since is not None for tr in tracks.values()),
                     "fall_alert": any(o.get("kind") == "fall" for o in res.get("observations", []))})
    cap.release()
    w = [r for r in rows if onset <= r["t"] <= onset + 5.0]
    return {"clip": clip["omnifall_path"], "split": clip["split"], "onset": onset, "frames": len(w),
            "seen_frac": sum(r["people"] > 0 for r in w) / max(len(w), 1),
            "lying": any(r["lying"] for r in w), "drop": any(r["drop"] for r in w), "collapse": any(r["collapse"] for r in w),
            "low": any(r["low"] for r in w), "alert": any(r["fall_alert"] for r in w),
            "first_seen_t": next((r["t"] for r in rows if r["people"] > 0), None), "duration": rows[-1]["t"] if rows else 0}


async def main():
    engine = VisionEngine(); engine.warm()
    out = [await run(engine, c) for c in clips]
    json.dump(out, open(sys.argv[3], "w"), indent=1)
    print(len(out), "fall clips diagnosed")

asyncio.run(main())
