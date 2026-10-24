"""A child the camera has lost (CLUADE.md failure table: "a child's track is lost ... then a child_not_visible event, low alert").

The tracker already calls a confirmed child "lost" after 2 s unseen. Alerting at that moment would fire on tracking
glitches, so three more checks apply before the low alert:
  * the child must STAY lost for `grace_s` (a new track that takes over the old identity cancels it);
  * the child must have been tracked for `min_age_s` (a flicker is not a child who was in the room);
  * nobody else may be standing where the child was last seen (`near_m`): a duplicate track dying while the same
    child is still visible under another track is not a missing child.
Adults (tagged from the dashboard) are never reported: a caregiver stepping out is normal.
"""
from dataclasses import dataclass, field

import numpy as np

from ..tracker import LostTrack


@dataclass
class NotVisibleConfig:
    grace_s: float = 1.0
    min_age_s: float = 3.0
    near_m: float = 1.0


@dataclass
class NotVisibleDetector:
    cfg: NotVisibleConfig = field(default_factory=NotVisibleConfig)
    _pending: dict = field(default_factory=dict)          # track id -> LostTrack waiting out the grace period

    def update(self, newly_lost: list[LostTrack], still_lost: list[LostTrack], visible_children: list[np.ndarray],
               ages: dict, t: float) -> list[LostTrack]:
        """newly_lost: tracks that just timed out. still_lost: every lost track the tracker still remembers (a track that
        was re-identified is no longer in it). visible_children: floor positions of untagged children seen this frame.
        ages: track id -> seconds it had been tracked. Returns the lost children to report now."""
        c = self.cfg
        for lost in newly_lost:
            if lost.tag is None and ages.get(lost.id, 0.0) >= c.min_age_s:
                self._pending[lost.id] = lost
        remembered = {l.id for l in still_lost}
        report = []
        for tid, lost in list(self._pending.items()):
            if tid not in remembered:                       # found again under the same identity (or forgotten): no alert
                del self._pending[tid]
            elif t - lost.lost_at >= c.grace_s:
                del self._pending[tid]
                if not any(float(np.hypot(*(p - lost.pos))) <= c.near_m for p in visible_children):
                    report.append(lost)
        return report
