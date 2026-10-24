"""DET-9 predictive zone warning on the floor plane (see docs/SPEC.md).

Ground points from the video are mapped to meters with a homography H fitted from
operator-clicked floor points. Each track runs a constant-velocity Kalman filter whose
measurement noise is the image noise pushed through H's Jacobian, so positions far from
the camera count as less certain. The warning is the probability, over sampled velocities,
that the straight-line path crosses into the zone within τ seconds.
"""
from __future__ import annotations

import numpy as np

TAU_S = 3.0
SAMPLES = 200
SIGMA_ACCEL = 1.5      # m/s², white-acceleration process noise
IMAGE_SIGMA = 0.01     # ground-point noise, fraction of the frame
FLOOR_SIGMA = 0.02     # m, floor-plane noise floor
VELOCITY_SIGMA = 0.5   # m/s, initial velocity uncertainty
MAX_ERROR_M = 0.15
WARN_ON, WARN_OFF = 0.5, 0.3
MIN_AGE_S = 0.5


def _apply(H, points):
    p = np.c_[points, np.ones(len(points))] @ H.T
    return p[:, :2] / p[:, 2:3]


def _flat(points):
    """True when points barely span 2-D (all nearly on one line)."""
    centered = points - points.mean(axis=0)
    s = np.linalg.svd(centered, compute_uv=False)
    return s[0] == 0 or s[-1] / s[0] < 1e-2


def inside(point, polygon) -> bool:
    x, y = point
    hit = False
    for (ax, ay), (bx, by) in zip(polygon, np.roll(polygon, -1, axis=0)):
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            hit = not hit
    return hit


class Calibration:
    """Homography from normalized image coordinates (0–1) to floor-plan meters."""

    def __init__(self, H, error_m: float, ignored: list[int], points: list[dict]):
        self.H, self.H_inv = np.asarray(H, float), np.linalg.inv(np.asarray(H, float))
        self.error_m, self.ignored, self.points = error_m, ignored, points
        self.worst_m = error_m

    @classmethod
    def fit(cls, points) -> 'Calibration':
        if not isinstance(points, list) or not 4 <= len(points) <= 20:
            raise ValueError('Mark between 4 and 20 floor points')
        try:
            image = np.array([p['image'] for p in points], float).reshape(-1, 2)
            floor = np.array([p['floor'] for p in points], float).reshape(-1, 2)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError('Each point needs an image position and a floor position') from exc
        if len(image) != len(points) or not (np.isfinite(image).all() and np.isfinite(floor).all()):
            raise ValueError('Each point needs an image position and a floor position')
        if (image < 0).any() or (image > 1).any() or (np.abs(floor) > 100).any():
            raise ValueError('Points must be on the video, and within 100 m of the floor-plan origin')
        for a in range(len(points)):
            for b in range(a):
                if np.linalg.norm(image[a] - image[b]) < 0.005 or np.linalg.norm(floor[a] - floor[b]) < 0.01:
                    raise ValueError(f'Points {b + 1} and {a + 1} are duplicates')
        if _flat(image) or _flat(floor):
            raise ValueError('Points lie on one line; spread them across the floor')
        import cv2
        method = cv2.RANSAC if len(points) >= 6 else 0
        H, mask = cv2.findHomography(image, floor, method, MAX_ERROR_M)
        if H is None or not np.isfinite(H).all() or abs(np.linalg.det(H)) < 1e-12:
            raise ValueError('These points do not define a floor plane')
        # Least squares (under 6 points) uses every point; only RANSAC's mask marks points as ignored.
        used = mask.ravel().astype(bool) if method == cv2.RANSAC and mask is not None else np.ones(len(points), bool)
        if used.sum() < 4:
            raise ValueError('Fewer than 4 points agree with each other; check the measurements')
        errors = np.linalg.norm(_apply(H, image) - floor, axis=1)[used]
        if errors.max() > MAX_ERROR_M:
            worst = int(np.flatnonzero(used)[errors.argmax()])
            raise ValueError(f'Point {worst + 1} is {errors.max():.2f} m from where the other points place it (limit {MAX_ERROR_M} m); check its measurement')
        calibration = cls(H, round(float(errors.mean()), 3), [i for i in range(len(points)) if not used[i]], points)
        calibration.worst_m = round(float(errors.max()), 3)
        return calibration

    @classmethod
    def from_dict(cls, data: dict) -> 'Calibration':
        calibration = cls(data['H'], data['error_m'], data.get('ignored', []), data.get('points', []))
        calibration.worst_m = data.get('worst_m', data['error_m'])
        return calibration

    def as_dict(self) -> dict:
        return {'H': self.H.tolist(), 'error_m': self.error_m, 'worst_m': self.worst_m, 'ignored': self.ignored, 'points': self.points}

    def to_floor(self, uv):
        p = self.H @ np.array([uv[0], uv[1], 1.0])
        return None if abs(p[2]) < 1e-9 else p[:2] / p[2]

    def to_image(self, xy):
        p = self.H_inv @ np.array([xy[0], xy[1], 1.0])
        return None if p[2] <= 1e-9 else [float(p[0] / p[2]), float(p[1] / p[2])]

    def jacobian(self, uv) -> np.ndarray:
        """∂(X, Y)/∂(u, v) of the projective map at uv."""
        h = self.H
        q = np.array([uv[0], uv[1], 1.0])
        x, y, w = h @ q
        return np.array([[(h[0, 0] * w - x * h[2, 0]) / w ** 2, (h[0, 1] * w - x * h[2, 1]) / w ** 2],
                         [(h[1, 0] * w - y * h[2, 0]) / w ** 2, (h[1, 1] * w - y * h[2, 1]) / w ** 2]])

    def zone_to_floor(self, polygon):
        mapped = [self.to_floor(v) for v in polygon]
        return None if any(m is None for m in mapped) else np.array(mapped)


class KalmanCV:
    """Constant-velocity Kalman filter on the floor plane; state (X, Y, Ẋ, Ẏ)."""

    def __init__(self, z, R, t: float):
        self.x = np.array([z[0], z[1], 0.0, 0.0])
        self.P = np.zeros((4, 4))
        self.P[:2, :2] = R
        self.P[2:, 2:] = np.eye(2) * VELOCITY_SIGMA ** 2
        self.t = t

    def step(self, z, R, t: float):
        dt = t - self.t
        if dt < 0:
            return
        if dt > 0:
            F = np.eye(4)
            F[0, 2] = F[1, 3] = dt
            g = np.array([[dt ** 2 / 2, 0], [0, dt ** 2 / 2], [dt, 0], [0, dt]])
            self.x = F @ self.x
            self.P = F @ self.P @ F.T + SIGMA_ACCEL ** 2 * g @ g.T
            self.t = t
        S = self.P[:2, :2] + R
        K = self.P[:, :2] @ np.linalg.inv(S)
        self.x = self.x + K @ (np.asarray(z) - self.x[:2])
        self.P = self.P - K @ S @ K.T

    @property
    def position(self):
        return self.x[:2]

    @property
    def velocity(self):
        return self.x[2:]

    @property
    def P_vv(self):
        return self.P[2:, 2:]


def entry_probability(position, velocity, P_vv, polygon, tau: float = TAU_S, n: int = SAMPLES, rng=None):
    """(P(entry ≤ τ), median entry time of the hits or None); (1.0, 0.0) when already inside."""
    poly, p = np.asarray(polygon, float), np.asarray(position, float)
    if inside(p, poly):
        return 1.0, 0.0
    rng = rng if rng is not None else np.random.default_rng()
    v = rng.multivariate_normal(np.asarray(velocity, float), np.asarray(P_vv, float), size=n, check_valid='ignore')
    a, e = poly, np.roll(poly, -1, axis=0) - poly
    ap = a - p
    cross = lambda m, k: m[..., 0] * k[..., 1] - m[..., 1] * k[..., 0]
    denom = cross(v[:, None, :], e[None, :, :])                       # (n, edges)
    with np.errstate(divide='ignore', invalid='ignore'):
        t = cross(ap[None, :, :], e[None, :, :]) / denom              # time along each sampled path
        s = cross(ap[None, :, :], v[:, None, :]) / denom              # position along the edge
    hit = (np.abs(denom) > 1e-12) & (t > 0) & (s >= 0) & (s <= 1)
    first = np.where(hit, t, np.inf).min(axis=1)
    within = first <= tau
    if not within.any():
        return 0.0, None
    return float(within.mean()), float(np.median(first[within]))


class ApproachMonitor:
    """Per-track warning state: on after 2 frames above 0.5, off below 0.3, on entry, or when forgotten."""

    def __init__(self, seed: int = 0):
        self.tracks: dict = {}
        self.rng = np.random.default_rng(seed)

    def forget(self, tid):
        """Drop a person's state; keys may be the track ID or (track ID, zone ID)."""
        self.tracks = {k: v for k, v in self.tracks.items() if k != tid and not (isinstance(k, tuple) and k[0] == tid)}

    def update(self, tid, foot_uv, t: float, calibration: Calibration | None, zone_floor) -> dict:
        status = {'p': 0.0, 'eta_s': None, 'warning': False, 'started': False, 'path': None, 'floor_path': None}
        if foot_uv is None or calibration is None or zone_floor is None:
            return status
        z = calibration.to_floor(foot_uv)
        if z is None:
            return status
        J = calibration.jacobian(foot_uv)
        R = J @ (np.eye(2) * IMAGE_SIGMA ** 2) @ J.T + np.eye(2) * FLOOR_SIGMA ** 2
        track = self.tracks.get(tid)
        if track is None:
            track = self.tracks[tid] = {'kf': KalmanCV(z, R, t), 'since': t, 'above': 0, 'warning': False}
        else:
            track['kf'].step(z, R, t)
        kf = track['kf']
        if inside(kf.position, zone_floor):
            track['above'], track['warning'] = 0, False
            return {**status, 'p': 1.0, 'eta_s': 0.0}
        if t - track['since'] < MIN_AGE_S:
            return status
        p, eta = entry_probability(kf.position, kf.velocity, kf.P_vv, zone_floor, rng=self.rng)
        track['above'] = track['above'] + 1 if p > WARN_ON else 0
        started = not track['warning'] and track['above'] >= 2
        if started:
            track['warning'] = True
        elif track['warning'] and p < WARN_OFF:
            track['warning'] = False
        end = kf.position + kf.velocity * min(TAU_S, eta if eta is not None else TAU_S)
        ahead, here = calibration.to_image(end), calibration.to_image(kf.position)
        path = [[round(c, 4) for c in here], [round(c, 4) for c in ahead]] if here and ahead else None
        floor_path = [[round(float(c), 3) for c in kf.position], [round(float(c), 3) for c in end]]
        return {'p': round(p, 2), 'eta_s': round(eta, 1) if eta is not None else None, 'warning': track['warning'], 'started': started, 'path': path, 'floor_path': floor_path}
