"""Draw pose skeletons and feet points on a webcam, video file, stream URL or image, with timing.

  python scripts/live_pose.py 0                      # webcam, opens a window (press q to quit)
  python scripts/live_pose.py clip.mp4 --save out.mp4
  python scripts/live_pose.py photo.jpg --save out.png --weights ../weights/yolo26s-pose.pt
"""
import argparse, sys, time
import cv2
import numpy as np
sys.path.insert(0, ".")
from nestwatch_vision.capture import classify, open_source
from nestwatch_vision.config import PoseConfig
from nestwatch_vision.pose import PoseModel, foot_point

BONES = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
         (0, 1), (0, 2), (1, 3), (2, 4)]
QUALITY_COLOR = {"ankles": (0, 160, 0), "one_ankle": (0, 140, 255), "box_bottom": (0, 0, 220)}   # green / orange / red (BGR)


def draw(img, people, fps_text=""):
    for p in people:
        x1, y1, x2, y2 = p.box.astype(int)
        cv2.rectangle(img, (x1, y1), (x2, y2), (200, 200, 200), 1)
        for a, b in BONES:
            pa, pb = p.kp(a), p.kp(b)
            if pa and pb:
                cv2.line(img, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])), (255, 120, 0), 2)
        for i in range(17):
            k = p.kp(i)
            if k:
                cv2.circle(img, (int(k[0]), int(k[1])), 3, (0, 255, 255), -1)
        f = foot_point(p)
        cv2.circle(img, (int(f.u), int(f.v)), 8, QUALITY_COLOR[f.quality], -1)
        cv2.circle(img, (int(f.u), int(f.v)), 9, (255, 255, 255), 1)
        cv2.putText(img, f"{p.box_conf:.2f} {f.quality}", (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        cv2.putText(img, f"{p.box_conf:.2f} {f.quality}", (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    if fps_text:
        cv2.putText(img, fps_text, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--weights", default="../weights/yolo26n-pose.pt")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--save")
    a = ap.parse_args()
    model = PoseModel(PoseConfig(weights=a.weights, device=a.device, imgsz=a.imgsz))
    print(f"device: {model.device}")

    if a.source.lower().endswith((".jpg", ".jpeg", ".png")):
        img = cv2.imread(a.source)
        t0 = time.perf_counter(); people = model.infer(img); ms = (time.perf_counter() - t0) * 1000
        out = draw(img, people, f"{len(people)} people, {ms:.0f} ms")
        if a.save:
            cv2.imwrite(a.save, out)
        print(f"{len(people)} people; feet: {[foot_point(p).quality for p in people]}")
        return

    src = open_source(a.source)
    if hasattr(src, "start"):
        src.start()
    writer, times = None, []
    for f in src.frames():
        t0 = time.perf_counter(); people = model.infer(f.image); times.append(time.perf_counter() - t0)
        fps = 1 / np.mean(times[-30:])
        out = draw(f.image, people, f"{fps:.0f} fps (model only)  dropped {getattr(src, 'dropped', 0)}")
        if a.save:
            if writer is None:
                h, w = out.shape[:2]
                writer = cv2.VideoWriter(a.save, cv2.VideoWriter_fourcc(*"mp4v"), 15.0, (w, h))
            writer.write(out)
        else:
            cv2.imshow("ollo pose (q to quit)", out)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    src.stop()
    if writer:
        writer.release()
    if times:
        print(f"{len(times)} frames, model {np.mean(times) * 1000:.1f} ms average ({1 / np.mean(times):.0f} fps), dropped {getattr(src, 'dropped', 0)}")


if __name__ == "__main__":
    main()
