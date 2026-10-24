"""Zones as the vision service sees them: polygons in meters with a status and a schedule. See MATH.md section 5.4."""
from dataclasses import dataclass, field
from datetime import datetime
import numpy as np
from shapely.geometry import Polygon as SPolygon

PADDING_M = 0.02   # points exactly on an edge are a coin flip in the ray test; a 2 cm margin makes that moot (MATH 5.1)


def _opt(v):
    """Spacetime options arrive as None, {"some": x}, or already unwrapped."""
    if isinstance(v, dict):
        return v.get("some")
    return v


@dataclass
class Zone:
    id: str
    name: str
    polygon: np.ndarray            # (n, 2) meters, already padded
    severity: str
    status: str = "active"         # draft | active | off
    named_schedule: str | None = None
    start_min: int | None = None   # minutes after midnight
    end_min: int | None = None
    escalation: str = ""

    @staticmethod
    def from_row(row: dict) -> "Zone":
        pts = [(p["x"], p["y"]) for p in row["polygon"]]
        sched = row.get("schedule") or {}
        raw = SPolygon(pts)
        padded = raw.buffer(PADDING_M, join_style=2)               # mitre corners keep the shape square
        return Zone(
            id=row["id"], name=row["name"],
            polygon=np.array(padded.exterior.coords[:-1]),
            severity=row["severity"], status=row.get("status", "active"),
            named_schedule=_opt(sched.get("named")), start_min=_opt(sched.get("startMin", sched.get("start_min"))),
            end_min=_opt(sched.get("endMin", sched.get("end_min"))),   # camelCase from the web bindings, snake_case from SQL
            escalation=row.get("escalation", ""),
        )

    def active_at(self, now: datetime, named: dict[str, tuple[int, int]]) -> bool:
        """Is this zone in force right now? `named` maps a schedule name like "nap_time" to (start_min, end_min)."""
        if self.status != "active":
            return False
        start, end = self.start_min, self.end_min
        if self.named_schedule:
            if self.named_schedule not in named:
                return False                                       # unknown schedule: do not guess, stay quiet and let the dashboard fix it
            start, end = named[self.named_schedule]
        if start is None or end is None:
            return True                                            # no schedule: always on
        m = now.hour * 60 + now.minute
        return start <= m < end if start <= end else (m >= start or m < end)   # a window may wrap past midnight


@dataclass
class ZoneCache:
    zones: list[Zone] = field(default_factory=list)
    named_schedules: dict[str, tuple[int, int]] = field(default_factory=dict)

    def load(self, rows: list[dict]) -> None:
        self.zones = [Zone.from_row(r) for r in rows]

    def active(self, now: datetime) -> list[Zone]:
        return [z for z in self.zones if z.active_at(now, self.named_schedules)]
