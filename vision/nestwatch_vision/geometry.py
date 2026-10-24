"""Zone geometry on the floor plane, in meters. See MATH.md section 5."""
import numpy as np

Polygon = np.ndarray  # shape (n, 2), vertices in order


def as_poly(poly) -> np.ndarray:
    return np.asarray(poly, dtype=float).reshape(-1, 2)


def points_in_polygon(points, poly) -> np.ndarray:
    """Ray casting (MATH 5.1). points: (N, 2) or (2,). Returns bool array (N,) or a bool."""
    pts = np.asarray(points, dtype=float)
    single = pts.ndim == 1
    pts = pts.reshape(-1, 2)
    poly = as_poly(poly)
    px, py = pts[:, 0], pts[:, 1]
    inside = np.zeros(len(pts), dtype=bool)
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if yi != yj:
            crosses = ((yi > py) != (yj > py)) & (px < (xj - xi) * (py - yi) / (yj - yi) + xi)
            inside ^= crosses
        j = i
    return bool(inside[0]) if single else inside


def distance_to_polygon(points, poly) -> np.ndarray:
    """Unsigned distance to the polygon boundary (MATH 5.2)."""
    pts = np.asarray(points, dtype=float)
    single = pts.ndim == 1
    pts = pts.reshape(-1, 2)
    poly = as_poly(poly)
    best = np.full(len(pts), np.inf)
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        e = b - a
        t = np.clip(((pts - a) @ e) / max(e @ e, 1e-18), 0.0, 1.0)
        d = np.linalg.norm(pts - (a + t[:, None] * e), axis=1)
        best = np.minimum(best, d)
    return float(best[0]) if single else best


def signed_distance(points, poly) -> np.ndarray:
    """Negative inside the polygon, positive outside."""
    d = distance_to_polygon(points, poly)
    inside = points_in_polygon(points, poly)
    return np.where(inside, -d, d) if np.ndim(d) else (-d if inside else d)


def entry_times(positions, velocities, poly) -> np.ndarray:
    """Seconds until each point, moving in a straight line, first enters the polygon (MATH 5.3).

    0 if already inside, inf if the path never reaches it. positions, velocities: (N, 2).
    """
    p = np.asarray(positions, dtype=float).reshape(-1, 2)
    v = np.asarray(velocities, dtype=float).reshape(-1, 2)
    poly = as_poly(poly)
    best = np.full(len(p), np.inf)
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        e = b - a
        den = v[:, 0] * e[1] - v[:, 1] * e[0]              # v x e
        ap = a - p
        with np.errstate(divide="ignore", invalid="ignore"):
            t = (ap[:, 0] * e[1] - ap[:, 1] * e[0]) / den     # (a-p) x e / den
            s = (ap[:, 0] * v[:, 1] - ap[:, 1] * v[:, 0]) / den  # (a-p) x v / den
        hit = (np.abs(den) > 1e-12) & (t >= 0) & (s >= 0) & (s <= 1)
        best = np.where(hit, np.minimum(best, t), best)
    best[points_in_polygon(p, poly)] = 0.0
    return best


def time_to_entry(position, velocity, poly) -> float:
    return float(entry_times(np.asarray(position)[None, :], np.asarray(velocity)[None, :], poly)[0])
