"""Build a demo "room" video from the GMDCSA24 dataset: the same person moving about, then a fall at the end.

    .venv/bin/python scripts/make_demo_room.py [OUT.mp4]            (default out/demo_room.mp4)
Then run it as the camera:   .venv/bin/python -m nestwatch_vision.main out/demo_room.mp4 --realtime --demo-map
The clips are Subject 1, one fixed camera in one room (GMDCSA24, MIT licence). Every picture is kept as it is.
"""
import sys
from pathlib import Path

import cv2

DATA = Path.home() / "Hackathons/datasets/gmdcsa24/Subject 1"
PLAN = ["ADL/08", "ADL/05", "ADL/11", "ADL/02", "Fall/04"]          # walking and everyday movement, then the fall
FPS, SIZE = 15, (960, 540)

out = Path(sys.argv[1] if len(sys.argv) > 1 else "out/demo_room.mp4")
out.parent.mkdir(parents=True, exist_ok=True)
w = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"avc1"), FPS, SIZE)
t_total, marks = 0.0, []
for name in PLAN:
    cap = cv2.VideoCapture(str(DATA / f"{name}.mp4"))
    step = max(1, round((cap.get(cv2.CAP_PROP_FPS) or 30) / FPS))
    n = i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % step == 0:
            w.write(cv2.resize(f, SIZE, interpolation=cv2.INTER_AREA))
            n += 1
        i += 1
    marks.append((name, round(t_total, 1)))
    t_total += n / FPS
w.release()
print(f"wrote {out}: {t_total:.0f} s at {FPS} fps, {SIZE[0]}x{SIZE[1]}")
print("clips start at:", ", ".join(f"{n} {t}s" for n, t in marks))
