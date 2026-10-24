"""Calibrate a camera: click the floor markers in the picture, in the same order as their floor positions.

  python scripts/calibrate.py 0 --floor "0,0;4,0;4,3;0,3;2,0;2,3"          # webcam, 6 markers, you click them
  python scripts/calibrate.py clip.mp4 --floor "..."                        # from a frame of a video
  python scripts/calibrate.py --points points.json                          # no clicking: [{"pixel":[u,v],"floor":[x,y]}, ...]

Floor positions are meters from the room's top-left corner (x right, y down), the same as the dashboard floor plan.
Use 6 or more markers: with 4 the fit error is zero by construction and cannot catch a mis-click (MATH.md 1.6).
"""
import argparse, json, sys, time
import numpy as np
sys.path.insert(0, ".")
from nestwatch_vision.calibration import CalibrationError, calibrate
from nestwatch_vision.capture import open_source
from nestwatch_vision.sync import SpacetimeHttp


def grab_frame(source):
    src = open_source(source)
    if hasattr(src, "start"):
        src.start(); time.sleep(1.0)                         # let a webcam's exposure settle
    for f in src.frames():
        img = f.image
        break
    src.stop()
    return img


def click_points(img, n):
    import cv2
    pts, shown = [], img.copy()

    def on_mouse(event, x, y, *_):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < n:
            pts.append((x, y))
            cv2.circle(shown, (x, y), 6, (0, 255, 255), -1)
            cv2.putText(shown, str(len(pts)), (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    cv2.namedWindow("calibrate")
    cv2.setMouseCallback("calibrate", on_mouse)
    while len(pts) < n:
        cv2.imshow("calibrate", shown)
        if cv2.waitKey(30) & 0xFF == ord("q"):
            raise SystemExit("cancelled")
    cv2.imshow("calibrate", shown); cv2.waitKey(400); cv2.destroyAllWindows()
    return pts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?")
    ap.add_argument("--floor", help='floor positions in meters, in click order: "x,y;x,y;..."')
    ap.add_argument("--points")
    ap.add_argument("--camera", default="cam1")
    ap.add_argument("--room", default="main")
    ap.add_argument("--uri", default="http://127.0.0.1:3000")
    ap.add_argument("--db", default="nestwatch-test")
    ap.add_argument("--token-file", default="../tools/.vision-token")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args()

    if a.points:
        pairs = json.load(open(a.points))
        pix = np.array([p["pixel"] for p in pairs], float); flr = np.array([p["floor"] for p in pairs], float)
    else:
        flr = np.array([[float(v) for v in p.split(",")] for p in a.floor.split(";")])
        print(f"click the {len(flr)} markers in this order: " + "  ".join(f"{i + 1}=({x:g},{y:g})" for i, (x, y) in enumerate(flr)))
        pix = np.array(click_points(grab_frame(a.source), len(flr)), float)

    try:
        r = calibrate(pix, flr)
    except CalibrationError as e:
        raise SystemExit(f"cannot calibrate: {e}")
    print(f"fit error {r.rms_m * 100:.1f} cm over {len(flr)} points; per point (cm): {[round(e * 100, 1) for e in r.per_point_m]}")
    if r.holdout_m:
        print(f"each point predicted from the others (cm): {[round(e * 100, 1) for e in r.holdout_m]}")
    for w in r.warnings:
        print("note:", w)
    if not r.ok:
        raise SystemExit("not saved: the calibration is not good enough")
    flat = [float(v) for v in r.H.reshape(9)]
    out = a.out or f"calibration_{a.camera}.json"
    json.dump({"camera": a.camera, "homography": flat, "pixel": pix.tolist(), "floor": flr.tolist(), "rms_m": r.rms_m}, open(out, "w"), indent=2)
    print("saved", out)
    if not a.no_upload:
        client = SpacetimeHttp(a.uri, a.db, open(a.token_file).read().strip())
        client.call("upsert_camera", [a.camera, a.room, a.camera, flat, []])
        print(f"uploaded the homography for {a.camera}")


if __name__ == "__main__":
    main()
