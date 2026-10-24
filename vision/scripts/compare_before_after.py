"""Side-by-side video: LEFT = the original dataset video (before), RIGHT = the same video with the team's detector applied (after).

    python scripts/compare_before_after.py ORIGINAL.mp4 PREVIEW.mp4 OUT.mp4 "title"
PREVIEW.mp4 comes from render_preview.py (12 fps). The original is sampled onto the same 12 fps timeline.
"""
import sys
import cv2
import numpy as np

orig, prev, out, title = sys.argv[1:5]
a, b = cv2.VideoCapture(orig), cv2.VideoCapture(prev)
fps_a, fps_b = a.get(cv2.CAP_PROP_FPS) or 30.0, b.get(cv2.CAP_PROP_FPS) or 12.0
ok, fb = b.read()
H, W = fb.shape[:2]                                  # preview size: picture + 70 px label bar
vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"avc1"), fps_b, (2 * W, H + 40))
pad = lambda im: cv2.copyMakeBorder(im, 40, 0, 0, 0, cv2.BORDER_CONSTANT, value=(30, 30, 30))


def caption(img, s, color):
    cv2.putText(img, s, (10, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
    return img


n = 0
while ok:
    t = n / fps_b
    a.set(cv2.CAP_PROP_POS_FRAMES, int(round(t * fps_a)))
    oka, fa = a.read()
    if not oka:
        fa = np.zeros((H - 70, W, 3), np.uint8)
    fa = cv2.resize(fa, (W, H - 70))
    left = cv2.copyMakeBorder(fa, 0, 70, 0, 0, cv2.BORDER_CONSTANT, value=(30, 30, 30))
    cv2.putText(left, f"t={t:4.1f}s   the video as recorded, no detector", (8, H - 46), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
    cv2.putText(left, title, (8, H - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)
    frame = np.hstack([caption(pad(left), "BEFORE: original video", (255, 255, 255)), caption(pad(fb), "AFTER: team's detector applied", (120, 255, 120))])
    vw.write(frame)
    ok, fb = b.read()
    n += 1
vw.release()
print("wrote", out, f"{2 * W}x{H + 40}, {n} frames")
