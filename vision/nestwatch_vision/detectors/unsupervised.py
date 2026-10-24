"""Unsupervised child: no tagged adult nearby for a sustained time. See MATH.md section 8.4.

Evidence per frame is a soft step in the distance (in meters, on the floor) from the child to the nearest visible adult:
    e = 1 / (1 + exp(-(d - R) / w))     about 0 well inside R, 0.5 at R, about 1 well beyond it
and 1 when no adult is visible at all. CUSUM (leak k, threshold h, in evidence-seconds) turns that into an alert, so it
takes about h / (e - k) seconds of being alone: 10 s at full evidence with the defaults.
Adults are only known once a caregiver tags them on the dashboard, so the detector stays OFF until at least one person
has been tagged; otherwise every person would count as a child alone.
"""
from dataclasses import dataclass
import math


@dataclass
class UnsupervisedConfig:
    radius_m: float = 2.0          # R
    softness_m: float = 0.4        # w
    k: float = 0.5
    h: float = 5.0
    cooldown_s: float = 120.0


def evidence(child_xy, adults_xy, cfg: UnsupervisedConfig) -> float:
    if not adults_xy:
        return 1.0
    d = min(math.hypot(child_xy[0] - a[0], child_xy[1] - a[1]) for a in adults_xy)
    z = (d - cfg.radius_m) / cfg.softness_m
    return 1.0 / (1.0 + math.exp(-max(min(z, 50.0), -50.0)))
