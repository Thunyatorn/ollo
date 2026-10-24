"""Render preview videos: the team's detector running on OmniFall/GMDCSA24 clips, with the dataset's labels beside it.

    /path/to/ollo-remote/.venv/bin/python scripts/render_preview.py LABELS_JSON OUT_DIR [clip substring ...]

For each clip it runs the team's VisionEngine exactly as their evaluator does (12 fps, 640 px wide), then draws:
 - skeleton and track id of everyone their pose tracker sees
 - top bar: the time, and the dataset's LABEL at that moment (for example "fall", "sitting")
 - a red banner "FALL ALERT" for 2 s after their detector raises a fall (any other alert kind in orange)
 - a verdict line at the end: HIT (alert within 5 s of the labelled onset), MISSED, or FALSE ALARM
The clip is written as H.264 so a browser or QuickTime can play it.
"""
import asyncio, base64, json, sys
from pathlib import Path
import cv2
sys.path.insert(0, "/Users/blackslex/Hackathons/ollo-remote")
from server.vision import VisionEngine

BONES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (0, 1), (0, 2), (1, 3), (2, 4)]
FPS_OUT, HIT = 12.0, 5.0


def label_at(segs, t):
    for name, s, e in segs:
        if s <= t < e:
            return name
    return segs[-1][0] if segs else ""


def text(img, s, org, scale, color, thick=2):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 3)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick)


async def render(engine, clip, labels_dir, out_dir):
    path = (labels_dir / clip["path"]).resolve()
    cap = cv2.VideoCapture(str(path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    engine.configure(clip.get("settings", {}))
    frames, alerts, idx, nxt, seq = [], [], 0, 0.0, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / src_fps; idx += 1
        if t + 1e-6 < nxt:
            continue
        nxt += 1 / FPS_OUT
        if frame.shape[1] != 640:
            frame = cv2.resize(frame, (640, round(640 * frame.shape[0] / frame.shape[1])))
        jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])[1].tobytes()
        res = await engine.process_frame({"session_id": "prev", "epoch": 1, "frame_seq": seq, "media_time_ms": t * 1000, "image": base64.b64encode(jpeg).decode()})
        seq += 1
        new = [o["kind"] for o in res.get("observations", []) if o.get("kind") in ("fall", "distress", "rhythmic", "stillness", "approach", "boundary")]
        for k in new:
            alerts.append((k, t))
        frames.append((t, frame, res.get("overlays", []), new))
    cap.release()

    onsets = [e["onset_s"] for e in clip["events"]]
    falls = sorted(t for k, t in alerts if k == "fall")
    if onsets:
        verdict = ("HIT: fall alert %.1fs after the labelled fall" % (min(f for f in falls if onsets[0] <= f <= onsets[0] + HIT) - onsets[0])) \
            if any(onsets[0] <= f <= onsets[0] + HIT for f in falls) else "MISSED: no fall alert within 5s of the labelled fall"
    else:
        verdict = ("FALSE ALARM: fall alert on a clip with no fall" if falls else "CORRECT: no fall alert (clip has no fall)")
    color_v = (0, 160, 0) if verdict.startswith(("HIT", "CORRECT")) else (0, 0, 255)

    name = clip["omnifall_path"].replace("/", "_")
    h, w = frames[0][1].shape[:2]
    out_dir.mkdir(parents=True, exist_ok=True)
    vw = cv2.VideoWriter(str(out_dir / f"{name}.mp4"), cv2.VideoWriter_fourcc(*"avc1"), FPS_OUT, (w, h + 70))
    banner_until, banner_kind = -1, ""
    for t, frame, overlays, new in frames:
        img = frame.copy()
        for o in overlays:
            kp = o.get("keypoints") or []
            pts = [(int(k[0] * w), int(k[1] * h), k[2]) for k in kp]
            for a, b in BONES:
                if a < len(pts) and b < len(pts) and pts[a][2] > 0.4 and pts[b][2] > 0.4:
                    cv2.line(img, pts[a][:2], pts[b][:2], (255, 140, 0), 2)
            x1, y1, x2, y2 = int(o["x"] * w), int(o["y"] * h), int((o["x"] + o["width"]) * w), int((o["y"] + o["height"]) * h)
            cv2.rectangle(img, (x1, y1), (x2, y2), (200, 200, 200), 1)
            text(img, str(o.get("label", ""))[:14], (x1, max(14, y1 - 4)), 0.45, (255, 255, 255), 1)
        for k in new:
            if k == "fall" or t > banner_until:
                banner_until, banner_kind = t + 2.0, k
        if t <= banner_until:
            cv2.rectangle(img, (0, h // 2 - 22), (w, h // 2 + 22), (0, 0, 220) if banner_kind == "fall" else (0, 140, 255), -1)
            text(img, f"{banner_kind.upper()} ALERT (their detector)", (12, h // 2 + 9), 0.8, (255, 255, 255))
        bar = img.copy()[:0]
        canvas = cv2.copyMakeBorder(img, 0, 70, 0, 0, cv2.BORDER_CONSTANT, value=(30, 30, 30))
        lab = label_at(clip["segments"], t)
        flag = "<< LABELLED FALL" if lab == "fall" else ""
        text(canvas, f"t={t:4.1f}s   dataset label: {lab} {flag}", (8, h + 24), 0.6, (255, 255, 255) if lab != "fall" else (80, 80, 255), 2)
        text(canvas, verdict, (8, h + 56), 0.55, color_v, 2)
        vw.write(canvas)
    vw.release()
    return name, verdict


async def main():
    labels = Path(sys.argv[1]); out = Path(sys.argv[2]); pick = sys.argv[3:]
    data = json.load(open(labels))["clips"]
    clips = [c for c in data if any(p in c["omnifall_path"] for p in pick)] if pick else data
    engine = VisionEngine(); engine.warm()
    for c in clips:
        name, verdict = await render(engine, c, labels.parent, out)
        print(f"{name:20s} {c['split']:5s} {verdict}")


asyncio.run(main())
