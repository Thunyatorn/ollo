"""Evidence that a person is about to enter a zone. See MATH.md section 6."""
from dataclasses import dataclass
import numpy as np

from .geometry import entry_times, points_in_polygon, time_to_entry

# Below RAMP_LO m/s the velocity estimate is mostly noise, so we ignore it; at RAMP_HI and above we trust it fully.
RAMP_LO, RAMP_HI = 0.05, 0.15


@dataclass
class Evidence:
    e: float                   # 0..1: fraction of plausible paths that reach the zone within the horizon
    entry_s: float | None      # time to entry along the mean path, None if it never gets there within the horizon
    inside: bool


def shrink_velocity(vel: np.ndarray, sigma2: float, c: float) -> np.ndarray:
    """Pull a velocity estimate toward zero when it is no bigger than its own noise (MATH 6.4).

    A standing child's estimated velocity is noise of about 0.2 to 0.5 m/s; a walking child's is well above it.
    factor = max(0, 1 - c * sigma^2 / speed^2): speed at the noise level gives 0, a clear walk keeps most of its speed.
    """
    s2 = float(vel @ vel)
    if s2 <= 0.0 or c <= 0.0:
        return vel
    return vel * max(0.0, 1.0 - c * sigma2 / s2)


def zone_evidence(x: np.ndarray, P: np.ndarray, poly, horizon: float = 3.0, n: int = 200,
                  rng: np.random.Generator | None = None, shrink_c: float = 0.5) -> Evidence:
    """x = [px, py, vx, vy] and P its 4x4 covariance, straight from the Kalman filter.

    Hit fraction (MATH 6.2): draw n plausible (position, velocity) pairs, run the exact ray test on each,
    and count the share that enter the polygon within `horizon` seconds.
    The velocity part is faded out below 0.15 m/s so a child standing at the edge does not accumulate evidence.
    """
    rng = rng or np.random.default_rng()
    pos = x[:2]
    vel = shrink_velocity(x[2:], float(P[2, 2] + P[3, 3]) / 2, shrink_c)
    if bool(points_in_polygon(pos, poly)):
        return Evidence(1.0, 0.0, True)                              # already there (MATH 6.3)
    speed = float(np.linalg.norm(vel))
    ramp = float(np.clip((speed - RAMP_LO) / (RAMP_HI - RAMP_LO), 0.0, 1.0))
    if ramp == 0.0:
        return Evidence(0.0, None, False)
    samples = rng.multivariate_normal(np.r_[pos, vel], P, size=n)
    t = entry_times(samples[:, :2], samples[:, 2:], poly)
    e = float(np.mean(t <= horizon)) * ramp
    mean_t = time_to_entry(pos, x[2:], poly)               # the countdown uses the real estimate; shrinkage only tempers the evidence
    return Evidence(e, mean_t if mean_t <= horizon else None, False)
