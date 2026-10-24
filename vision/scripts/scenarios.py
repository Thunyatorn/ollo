"""Scripted children for measuring the alert chain. Each factory takes a seed and returns a path t -> (x, y)."""
import numpy as np


def threat(seed):
    r = np.random.default_rng(1000 + seed)
    y, x0, sp = r.uniform(2.1, 2.8), r.uniform(0.3, 1.2), r.uniform(0.4, 1.0)
    ang, wait = np.radians(r.uniform(-12, 12)), r.uniform(0, 2)
    v = sp * np.array([np.cos(ang), np.sin(ang)])
    return lambda t: (x0, y) if t < wait else (x0 + v[0] * (t - wait), y + v[1] * (t - wait))


def parallel(seed):
    r = np.random.default_rng(2000 + seed)
    y, sp = r.uniform(0.3, 1.4), r.uniform(0.3, 0.9)
    return lambda t: (0.4 + sp * t, y)


def away(seed):
    r = np.random.default_rng(3000 + seed)
    sp = r.uniform(0.3, 0.9)
    return lambda t: (max(0.3, 2.0 - sp * t), 2.2)


def stand_near(seed):
    """Standing 0.4 to 1.2 m from the stairs edge."""
    r = np.random.default_rng(4000 + seed)
    d, y = r.uniform(0.4, 1.2), r.uniform(2.1, 2.8)
    return lambda t: (2.8 - d, y)


def stand_very_near(seed):
    """Standing 0.1 to 0.3 m from the edge: arguably worth an alert, so reported separately and not counted as a false alarm."""
    r = np.random.default_rng(4500 + seed)
    d, y = r.uniform(0.1, 0.3), r.uniform(2.1, 2.8)
    return lambda t: (2.8 - d, y)


def stand_far(seed):
    return lambda t: (1.0, 1.0)


def wander(seed):
    """Walking between random spots in the left 60% of the room at up to 0.8 m/s, never closer than 1 m to the stairs."""
    r = np.random.default_rng(5000 + seed)
    pts = [r.uniform([0.3, 0.3], [1.8, 2.8])]
    legs = []                                              # (start, end, duration)
    for _ in range(7):
        nxt = r.uniform([0.3, 0.3], [1.8, 2.8])
        legs.append((pts[-1], nxt, max(1.0, np.linalg.norm(nxt - pts[-1]) / r.uniform(0.3, 0.8))))
        pts.append(nxt)
    ends = np.cumsum([d for _, _, d in legs])

    def f(t):
        i = int(min(np.searchsorted(ends, t), len(legs) - 1))
        a_, b_, d = legs[i]
        t0 = ends[i] - d
        u = np.clip((t - t0) / d, 0, 1)
        return tuple(a_ * (1 - u) + b_ * u)
    return f


def play_near(seed):
    """Strolling in a loop 1.0 to 1.4 m from the stairs edge at 0.4 m/s."""
    r = np.random.default_rng(6000 + seed)
    cx, cy, rad, ph = 1.5, 2.2, r.uniform(0.3, 0.5), r.uniform(0, 6.28)
    w = 0.4 / rad
    return lambda t: (cx + rad * np.cos(w * t + ph), cy + rad * np.sin(w * t + ph))


NON_THREATS = {"walking parallel": parallel, "walking away": away, "standing 0.4-1.2m away": stand_near,
               "standing far": stand_far, "wandering": wander, "strolling near": play_near}
INFORMATIONAL = {"standing 0.1-0.3m from edge": stand_very_near}
