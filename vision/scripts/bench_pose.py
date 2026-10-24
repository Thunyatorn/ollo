"""Measure pose-model speed on this machine: python scripts/bench_pose.py"""
import os, sys, time
import cv2, numpy as np, ultralytics
sys.path.insert(0, ".")
from nestwatch_vision.config import PoseConfig
from nestwatch_vision.pose import PoseModel

src = cv2.imread(os.path.join(os.path.dirname(ultralytics.__file__), "assets", "bus.jpg"))
frame = cv2.resize(src, (1280, 720))                     # a typical webcam frame
W = "../weights"
print(f"{'model':16s} {'device':5s} {'imgsz':>5s} | {'median ms':>9s} {'p95 ms':>7s} {'fps':>6s} | people")
for name in ["yolo26n-pose.pt", "yolo26s-pose.pt"]:
    path = os.path.join(W, name)
    if not os.path.exists(path):
        from ultralytics import YOLO
        YOLO(name)                                       # downloads to the current directory
        os.replace(name, path)
    for device in ["cpu", "mps"]:
        for imgsz in [640, 480, 320]:
            m = PoseModel(PoseConfig(weights=path, device=device, imgsz=imgsz))
            for _ in range(5):
                m.infer(frame)
            ts = []
            for _ in range(40):
                t0 = time.perf_counter(); people = m.infer(frame); ts.append((time.perf_counter() - t0) * 1000)
            print(f"{name:16s} {device:5s} {imgsz:5d} | {np.median(ts):9.1f} {np.percentile(ts,95):7.1f} {1000/np.median(ts):6.1f} | {len(people)}")
