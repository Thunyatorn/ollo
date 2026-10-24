"""Talking to Spacetime over plain HTTP. Verified against a local server (see MATH.md section 12, decision 4).

  reducer call : POST /v1/database/<db>/call/<reducer>   body = JSON array of the arguments, in order
                 products are arrays in field order; an option is {"some": x} or {"none": []}
  SQL read     : POST /v1/database/<db>/sql              body = the SQL text; reply has a schema and rows
                 rows encode products as arrays and options as [0, value] (some) or [1, []] (none)
"""
from collections import deque
import json
import logging
import threading
import time
import requests

log = logging.getLogger("nestwatch.sync")


def decode(value, t):
    """Turn one SQL cell into plain Python using its schema type (None for an empty option)."""
    (kind, body), = t.items()
    if kind == "Array":
        return [decode(v, body) for v in value]
    if kind == "Product":
        names = [e["name"].get("some") or str(i) for i, e in enumerate(body["elements"])]
        return {n: decode(v, e["algebraic_type"]) for n, v, e in zip(names, value, body["elements"])}
    if kind == "Sum":
        tag, payload = value
        variant = body["variants"][tag]
        name = variant["name"].get("some")
        if {v["name"].get("some") for v in body["variants"]} == {"some", "none"}:     # an option
            return None if name == "none" else decode(payload, variant["algebraic_type"])
        return {name: decode(payload, variant["algebraic_type"])}
    return value                                                                   # String, F64, U16, Bool, ...


def rows(result: dict) -> list[dict]:
    types = [(e["name"].get("some"), e["algebraic_type"]) for e in result["schema"]["elements"]]
    return [{n: decode(v, t) for (n, t), v in zip(types, row)} for row in result["rows"]]


class SpacetimeHttp:
    def __init__(self, uri: str, db: str, token: str, timeout: float = 3.0):
        self.base = f"{uri.rstrip('/')}/v1/database/{db}"
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        self.timeout = timeout
        self.session = requests.Session()

    def call(self, reducer: str, args: list) -> None:
        r = self.session.post(f"{self.base}/call/{reducer}", headers=self.headers, data=json.dumps(args), timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"{reducer}: {r.status_code} {r.text[:160]}")

    def sql(self, query: str) -> list[dict]:
        r = self.session.post(f"{self.base}/sql", headers=self.headers, data=query, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"sql: {r.status_code} {r.text[:160]}")
        return rows(r.json()[0])

    # ---- reads the vision service needs -------------------------------------------------------
    def zones(self) -> list[dict]:
        return self.sql("SELECT id, room_id, name, polygon, severity, schedule, escalation, status FROM zone")

    def room(self, room_id: str) -> dict | None:
        found = self.sql(f"SELECT id, name, width_m, height_m FROM room WHERE id = '{room_id}'")
        return found[0] if found else None

    def camera(self, camera_id: str) -> dict | None:
        found = self.sql(f"SELECT id, room_id, name, homography, status FROM camera WHERE id = '{camera_id}'")
        return found[0] if found else None


def _opt(v):
    return {"none": []} if v is None else {"some": v}


class SpacetimeSink:
    """Sends positions and events from a background thread so a slow or dead network never stalls the camera loop.

    Positions are only useful fresh: only the newest batch is kept. Events are never dropped on purpose:
    they queue (up to `max_events`) and are retried in order until the server answers (MATH failure behaviour:
    "events queue and sync when the connection returns").
    """

    def __init__(self, client: SpacetimeHttp, max_events: int = 1000, retry_delay: float = 1.0):
        self.client, self.retry_delay = client, retry_delay
        self._positions = None
        self._events: deque = deque(maxlen=max_events)
        self._cv = threading.Condition()
        self._stop = False
        self.online, self.sent_positions, self.sent_events, self.errors = True, 0, 0, 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="spacetime-sink")
        self._thread.start()

    def positions(self, room_id: str, positions: list[dict]) -> None:
        with self._cv:
            self._positions = (room_id, positions)
            self._cv.notify()

    def event(self, track_id: str, event_type: str, zone_id: str, severity: str, predicted_entry_s, clip_ref: str) -> None:
        with self._cv:
            self._events.append(("report_event", [track_id, event_type, zone_id, severity, _opt(predicted_entry_s), clip_ref]))
            self._cv.notify()

    def reducer(self, name: str, args: list) -> None:
        """Any reducer call, queued in order with the events and retried if the server is unreachable."""
        with self._cv:
            self._events.append((name, args))
            self._cv.notify()

    def health(self, camera_id: str, status: str) -> None:
        with self._cv:
            self._events.append(("camera_health", [camera_id, status]))
            self._cv.notify()

    def pending(self) -> int:
        with self._cv:
            return len(self._events)

    def unsent_clips(self) -> set:
        """clip_refs of report_event calls still waiting to be delivered."""
        with self._cv:
            return {args[5] for name, args in self._events if name == "report_event"}

    def _run(self) -> None:
        while True:
            with self._cv:
                self._cv.wait_for(lambda: self._stop or self._positions is not None or self._events, timeout=0.5)
                if self._stop:
                    return
                pos, self._positions = self._positions, None
                ev = self._events[0] if self._events else None
            try:
                if pos is not None:
                    room_id, items = pos
                    self.client.call("update_positions", [room_id, [[p["trackId"], p["kind"], p["label"], p["x"], p["y"], p["vx"], p["vy"], p["visible"]] for p in items]])
                    self.sent_positions += 1
                if ev is not None:
                    self.client.call(*ev)
                    with self._cv:
                        self._events.popleft()
                    self.sent_events += 1
                self.online = True
            except requests.RequestException as e:      # network down or server restarting: keep everything and retry
                self.errors += 1
                if self.online:
                    log.warning("spacetime unreachable: %s", e)
                self.online = False
                time.sleep(self.retry_delay)
            except RuntimeError as e:                    # the server answered and refused (bad arguments, wrong role)
                self.errors += 1
                log.error("spacetime rejected a call, dropping it so it cannot block the queue: %s", e)
                with self._cv:
                    if ev is not None and self._events and self._events[0] is ev:
                        self._events.popleft()

    def flush(self, timeout: float = 5.0) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            with self._cv:
                if not self._events and self._positions is None:
                    return True
            time.sleep(0.02)
        return False

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify()
        self._thread.join(timeout=2.0)
