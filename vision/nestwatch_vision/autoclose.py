"""Closing a zone alert by itself (CLUADE.md flow 1, step 8: "Child 4 moves back to the play area: close_alert").

Only an alert someone already OWNS is closed, only for zone alerts, and only after the child has been SEEN clear of the
zone (at least `margin_m` outside it) for `clear_s` seconds in a row. A child the camera cannot see is not "clear":
the timer starts over, and the caregiver closes the alert in the app instead. Falls and other kinds are always
closed by a person.
"""
from typing import Callable

import numpy as np

from .geometry import signed_distance

ZONE_EVENTS = ("zone_entry", "zone_entry_predicted")


class AutoCloser:
    def __init__(self, close: Callable[[str, str], None], clear_s: float = 10.0, margin_m: float = 0.5):
        self.close, self.clear_s, self.margin_m = close, clear_s, margin_m
        self._clear_since: dict[str, float] = {}
        self.closed: set[str] = set()

    def update(self, alerts: list[dict], seen: dict[str, np.ndarray], zones: dict, t: float) -> list[str]:
        """alerts: rows with id, status, track_id, zone_id, event_type. seen: track id -> floor position of tracks the
        camera sees right now. zones: zone id -> Zone. Returns the alert ids closed this time."""
        done = []
        live = set()
        for a in alerts:
            aid = a["id"]
            if a.get("status") != "owned" or a.get("event_type") not in ZONE_EVENTS or aid in self.closed:
                continue
            live.add(aid)
            zone, pos = zones.get(a.get("zone_id")), seen.get(a.get("track_id"))
            outside = zone is not None and pos is not None and float(signed_distance(np.asarray([pos]), zone.polygon)[0]) >= self.margin_m
            if not outside:
                self._clear_since.pop(aid, None)
                continue
            since = self._clear_since.setdefault(aid, t)
            if t - since >= self.clear_s:
                self.close(aid, f"Child moved away from {zone.name} and stayed clear for {self.clear_s:.0f} s")
                self.closed.add(aid)
                done.append(aid)
        for gone in [k for k in self._clear_since if k not in live]:
            del self._clear_since[gone]
        return done
