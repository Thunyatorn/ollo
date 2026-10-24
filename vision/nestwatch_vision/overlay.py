"""What the dashboard's live camera view draws on top of the (already blurred) picture: the pose skeleton of each person
the model sees, and a banner when an alert has just been raised. Drawing happens on a copy, so saved clips stay clean."""
import cv2
import numpy as np

SKELETON = [(5, 7), (7, 9), (6, 8), (8, 10), (5, 6), (5, 11), (6, 12), (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
            (0, 1), (0, 2), (1, 3), (2, 4)]                       # COCO keypoint pairs
GREEN, AMBER, RED, WHITE = (60, 170, 60), (0, 170, 230), (30, 30, 200), (255, 255, 255)   # BGR


def draw(img: np.ndarray, people, scale: float, banner: str = "", conf: float = 0.25) -> np.ndarray:
    """A copy of `img` with a skeleton and box per person. `scale`: picture pixels per original-frame pixel.
    People under `conf` (the pose model's own confidence floor) are drawn in amber."""
    out = img.copy()
    for p in people:
        color = GREEN if p.box_conf >= conf else AMBER
        x1, y1, x2, y2 = (int(v * scale) for v in p.box)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 1)
        k = np.asarray(p.kpts, float)
        for a, b in SKELETON:
            if k[a, 2] >= 0.3 and k[b, 2] >= 0.3:
                cv2.line(out, (int(k[a, 0] * scale), int(k[a, 1] * scale)), (int(k[b, 0] * scale), int(k[b, 1] * scale)), color, 2, cv2.LINE_AA)
        for i in range(17):
            if k[i, 2] >= 0.3:
                cv2.circle(out, (int(k[i, 0] * scale), int(k[i, 1] * scale)), 3, WHITE, -1, cv2.LINE_AA)
    if banner:                                                        # a small red pill, centred at the top
        h, w = out.shape[:2]
        scale = max(0.45, min(0.7, w / 1100))
        (tw, th), _ = cv2.getTextSize(banner, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
        x1, y1 = max(4, (w - tw) // 2 - 12), 10
        cv2.rectangle(out, (x1, y1), (x1 + tw + 24, y1 + th + 14), RED, -1)
        cv2.putText(out, banner, (x1 + 12, y1 + th + 6), cv2.FONT_HERSHEY_SIMPLEX, scale, WHITE, 1, cv2.LINE_AA)
    return out


def no_signal(width: int = 640, height: int = 360, text: str = "Camera not sending pictures") -> np.ndarray:
    img = np.full((height, width, 3), 40, np.uint8)
    cv2.putText(img, text, (20, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, WHITE, 2, cv2.LINE_AA)
    return img
