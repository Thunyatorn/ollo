"""Camera pixels to floor meters with a homography. See MATH.md section 1."""
from dataclasses import dataclass, field
import numpy as np


class CalibrationError(ValueError):
    pass


def _normalizer(pts: np.ndarray) -> np.ndarray:
    """Hartley normalization (MATH 1.4): centroid to origin, mean distance sqrt(2)."""
    c = pts.mean(axis=0)
    mean_d = np.linalg.norm(pts - c, axis=1).mean()
    s = np.sqrt(2) / mean_d if mean_d > 0 else 1.0
    return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1.0]])


def _apply_T(T: np.ndarray, pts: np.ndarray) -> np.ndarray:
    return (pts @ T[:2, :2].T) + T[:2, 2]


def _design(src: np.ndarray, dst: np.ndarray):
    """Normalize both point sets and build the DLT matrix A (MATH 1.3, 1.4)."""
    Ts, Td = _normalizer(src), _normalizer(dst)
    s, d = _apply_T(Ts, src), _apply_T(Td, dst)
    rows = []
    for (u, v), (x, y) in zip(s, d):
        rows.append([-u, -v, -1, 0, 0, 0, x * u, x * v, x])
        rows.append([0, 0, 0, -u, -v, -1, y * u, y * v, y])
    return np.array(rows), Ts, Td


def conditioning(image_pts, floor_pts) -> float:
    """How well the markers pin down H: second-smallest over largest singular value of A.

    About 0.3 for a good layout (extra points on a line between corners are fine). Near 0 when the
    markers are collinear or cramped: 0.0035 with three of four in a line, 1e-18 with all four.
    """
    src = np.asarray(image_pts, dtype=float).reshape(-1, 2)
    dst = np.asarray(floor_pts, dtype=float).reshape(-1, 2)
    A, _, _ = _design(src, dst)
    S = np.linalg.svd(A, compute_uv=False)
    return float(S[7] / S[0])


MIN_CONDITIONING = 0.02   # below this the markers cannot define H: reject
WARN_CONDITIONING = 0.1   # below this the layout is thin or cramped: warn


def fit_homography(image_pts, floor_pts) -> np.ndarray:
    """Direct linear transform with normalization (MATH 1.3). Returns H with H[2, 2] = 1."""
    src = np.asarray(image_pts, dtype=float).reshape(-1, 2)
    dst = np.asarray(floor_pts, dtype=float).reshape(-1, 2)
    if len(src) != len(dst) or len(src) < 4:
        raise CalibrationError("need at least 4 matching points")
    A, Ts, Td = _design(src, dst)
    if conditioning(src, dst) < MIN_CONDITIONING:
        raise CalibrationError("the markers are nearly in a line or too close together; spread them around the floor")
    _, _, Vt = np.linalg.svd(A)
    Hn = Vt[-1].reshape(3, 3)
    H = np.linalg.inv(Td) @ Hn @ Ts
    if abs(H[2, 2]) < 1e-12:
        raise CalibrationError("degenerate homography")
    return H / H[2, 2]


def to_floor(H: np.ndarray, pixels) -> np.ndarray:
    """Map pixels to floor meters. pixels: (N, 2) or (2,)."""
    p = np.asarray(pixels, dtype=float)
    single = p.ndim == 1
    p = p.reshape(-1, 2)
    q = np.c_[p, np.ones(len(p))] @ H.T
    out = q[:, :2] / q[:, 2:3]
    return out[0] if single else out


def jacobian(H: np.ndarray, pixel) -> np.ndarray:
    """2x2 matrix of floor meters per pixel at a pixel (MATH 1.8)."""
    u, v = pixel
    w = H[2] @ np.array([u, v, 1.0])
    x, y = to_floor(H, (u, v))
    return np.array([
        [(H[0, 0] - x * H[2, 0]) / w, (H[0, 1] - x * H[2, 1]) / w],
        [(H[1, 0] - y * H[2, 0]) / w, (H[1, 1] - y * H[2, 1]) / w],
    ])


@dataclass
class CalibrationReport:
    H: np.ndarray
    rms_m: float                       # fit error on all points, meters
    per_point_m: list[float]
    holdout_m: list[float] | None      # leave-one-out error per point; None with only 4 points
    ok: bool
    bad_point: int | None = None       # index of the worst point when not ok
    warnings: list[str] = field(default_factory=list)


def _drop_rms(src: np.ndarray, dst: np.ndarray) -> list[float] | None:
    """Fit error of the remaining points after dropping each point in turn (needs 6 or more points).

    A single bad click shows up as the one point whose removal makes everything else fit.
    (Hold-out error is not used for blame: leaving out a corner is an extrapolation and blames the wrong point.)
    """
    n = len(src)
    if n < 6:
        return None
    out = []
    for i in range(n):
        keep = [j for j in range(n) if j != i]
        try:
            Hi = fit_homography(src[keep], dst[keep])
            out.append(float(np.sqrt(np.mean(np.sum((to_floor(Hi, src[keep]) - dst[keep]) ** 2, axis=1)))))
        except CalibrationError:
            out.append(float("inf"))
    return out


def calibrate(image_pts, floor_pts, max_error_m: float = 0.05) -> CalibrationReport:
    """Fit H and judge it honestly (MATH 1.6).

    4 points: the fit error is zero by construction, so it cannot catch a mis-click; we say so.
    5 points: we can tell something is off but not which point.
    6 or more: we also name the point whose removal makes the rest fit.
    """
    src = np.asarray(image_pts, dtype=float).reshape(-1, 2)
    dst = np.asarray(floor_pts, dtype=float).reshape(-1, 2)
    H = fit_homography(src, dst)
    per = np.linalg.norm(to_floor(H, src) - dst, axis=1)
    rms = float(np.sqrt(np.mean(per ** 2)))
    warnings: list[str] = []
    if conditioning(src, dst) < WARN_CONDITIONING:
        warnings.append("the markers cover a thin or small part of the floor; spread them out for a steadier result")
    holdout = None
    if len(src) >= 5:                      # informational only: how well each point is predicted by the others
        holdout = []
        for i in range(len(src)):
            keep = [j for j in range(len(src)) if j != i]
            try:
                holdout.append(float(np.linalg.norm(to_floor(fit_homography(src[keep], dst[keep]), src[i]) - dst[i])))
            except CalibrationError:
                holdout.append(float("inf"))
    drop = _drop_rms(src, dst)
    ok, bad = True, None
    if len(src) == 4:
        warnings.append("only 4 points: the fit error is zero by construction and cannot catch a mis-click; add 2 or more check points")
    elif rms > max_error_m or (drop is not None and rms > 0.02 and min(drop) < rms / 3):
        ok = False
        if drop is not None:
            bad = int(np.argmin(drop))
            warnings.append(f"point {bad + 1} looks wrong; re-click it or re-measure its floor position")
        else:
            warnings.append(f"fit error {rms * 100:.1f} cm: one of the points is off; add a sixth point so I can tell which")
    return CalibrationReport(H, rms, per.tolist(), holdout, ok, bad, warnings)


def demo_homography(frame_w: float, frame_h: float, room_w: float, room_h: float) -> np.ndarray:
    """Stretch the whole picture over the whole room. Only for demos and tests on videos nobody calibrated."""
    return np.array([[room_w / frame_w, 0, 0], [0, room_h / frame_h, 0], [0, 0, 1.0]])
