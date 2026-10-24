"""A fake phone: posts a video's frames to the phone-camera server like the phone page does (JPEG, one at a time).

  .venv/bin/python scripts/phone_sim.py out/pan_long.mp4 --url https://127.0.0.1:8443 --code abc123 [--fps 10] [--seconds 40]
  [--stop-at 15 --stop-for 8]   go quiet for a while, like a phone that was locked
The certificate is self-signed, so it is not verified (this is the local test tool only).
"""
import argparse
import time

import cv2
import requests
import urllib3

urllib3.disable_warnings()
ap = argparse.ArgumentParser()
ap.add_argument("video")
ap.add_argument("--url", default="https://127.0.0.1:8443")
ap.add_argument("--code", required=True)
ap.add_argument("--fps", type=float, default=10)
ap.add_argument("--seconds", type=float, default=40)
ap.add_argument("--stop-at", type=float, default=0)
ap.add_argument("--stop-for", type=float, default=0)
a = ap.parse_args()

cap, t0, sent, bad = cv2.VideoCapture(a.video), time.time(), 0, 0
s = requests.Session()
while time.time() - t0 < a.seconds:
    now = time.time() - t0
    if a.stop_for and a.stop_at <= now < a.stop_at + a.stop_for:
        time.sleep(0.2)
        continue
    ok, img = cap.read()
    if not ok:
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        continue
    h, w = img.shape[:2]
    img = cv2.resize(img, (960, round(h * 960 / w))) if w > 960 else img
    jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
    r = s.post(f"{a.url}/phone-frame", data=jpg, headers={"X-Pair-Code": a.code, "Content-Type": "image/jpeg"}, verify=False, timeout=5)
    sent += r.status_code == 204
    bad += r.status_code != 204
    time.sleep(max(0, 1 / a.fps - 0.01))
print(f"sent {sent} frames, refused {bad}, in {time.time() - t0:.0f} s")
