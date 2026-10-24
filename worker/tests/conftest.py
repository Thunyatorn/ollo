"""An in-memory stand-in for the parts of Spacetime the worker uses: a few tables, simple SQL, and the reducers'
key rules (copied from spacetime/spacetimedb/src/index.ts). Live checks against the real module are in README."""
import re
from types import SimpleNamespace

import pytest

from nestwatch_worker.config import Settings
from nestwatch_worker.spacetime import Rejected, camel


def unopt(v):
    return None if v == {"none": []} else v["some"]


class FakeSpacetime:
    def __init__(self):
        self.t = {k: [] for k in ("alert", "call_job", "incident_event", "zone", "named_area", "worker_contacts", "report", "room", "caregiver", "track_position")}
        self.roles: dict[str, dict] = {}            # token -> my_role row
        self.calls: list[tuple[str, list]] = []
        self.token = "worker-token"
        self.down = False
        self._n = 100

    def nid(self, prefix):
        self._n += 1
        return f"{prefix}_{self._n}"

    def log(self, alert_id, kind, text, at=1000.0):
        self.t["incident_event"].append({"id": self.nid("e"), "alertId": alert_id, "at": at, "kind": kind, "text": text, "clipRef": None})

    # ---- SQL: SELECT cols FROM table [WHERE a = 'x' AND b != 'y' OR ...] ----
    async def sql(self, query, token=None):
        if self.down:
            import httpx
            raise httpx.ConnectError("down")
        m = re.fullmatch(r"SELECT (.+?) FROM (\w+)(?: WHERE (.+))?", query.strip())
        cols, table, where = m.groups()
        if table == "my_role":
            row = self.roles.get(token)
            if token == "forged":
                raise Rejected("sql: 401")
            data = [row] if row else []
        else:
            data = self.t[table]
        if where:
            def holds(row, cond):
                c, op, v = re.fullmatch(r"(\w+) (=|!=) '(.*)'", cond.strip()).groups()
                return (row.get(camel(c)) == v) == (op == "=")
            data = [r for r in data if any(all(holds(r, c) for c in part.split(" AND ")) for part in where.split(" OR "))]
        if cols.strip() != "*":
            names = [camel(c.strip()) for c in cols.split(",")]
            data = [{n: r.get(n) for n in names} for r in data]
        return [dict(r) for r in data]

    async def call(self, reducer, args):
        self.calls.append((reducer, args))
        a = lambda i: next((x for x in self.t["alert"] if x["id"] == i), None)
        if reducer == "update_call_job":
            job = next(j for j in self.t["call_job"] if j["id"] == args[0])
            if job["status"] != "cancelled":
                job["status"] = args[1]
        elif reducer == "acknowledge_alert":
            al = a(args[0])
            if al["ownerId"]:
                return
            if al["status"] not in ("open", "notified", "escalated", "unanswered"):
                raise Rejected(f"alert is {al['status']}")
            al.update(ownerId=args[1], status="owned", ackedVia=args[2])
            for j in self.t["call_job"]:
                if j["alertId"] == args[0] and j["status"] in ("queued", "ringing"):
                    j["status"] = "cancelled"
        elif reducer == "decline_alert":
            al = a(args[0])
            if al["ownerId"] or al["status"] not in ("notified", "escalated"):
                return
            self.log(args[0], "declined", f"{args[1]} cannot respond (via {args[2]}); escalating now")
            al["status"] = "escalated" if al["status"] == "notified" else "unanswered"
        elif reducer == "set_urgency":
            al = a(args[0])
            if al["severity"] == "high":
                raise Rejected("high alerts cannot be changed")
            al.update(severity=args[2], urgencyNote=args[1])
        elif reducer == "save_report":
            alert_id = unopt(args[0])
            if alert_id:
                al = a(alert_id)
                if al["status"] != "closed":
                    raise Rejected("reports are written for closed alerts")
                valid = {e["id"] for e in self.t["incident_event"] if e["alertId"] == alert_id}
                for line in args[2]:
                    if line[0] not in valid:
                        raise Rejected(f"unknown event {line[0]}")
                al["status"] = "reported"
            self.t["report"].append({"id": self.nid("r"), "kind": "incident" if alert_id else "daily", "alertId": alert_id,
                                     "summary": args[1], "lines": args[2], "status": "draft"})
        elif reducer == "save_zone_draft":
            area = next((x for x in self.t["named_area"] if x["roomId"] == args[0] and x["name"].lower() == args[1].lower()), None)
            if not area:
                raise Rejected("no named area")
            self.t["zone"].append({"id": self.nid("zd"), "roomId": args[0], "name": area["name"], "status": "draft",
                                   "schedule": args[2], "severity": args[3], "escalation": args[4]})
        elif reducer == "escalate_due":
            pass
        else:
            raise AssertionError(f"unexpected reducer {reducer}")


def make_alert(stdb, id="a_1", severity="high", status="notified", created=1000.0, event="zone_entry", zone="z_stairs",
               track="t4", clip="evt_1"):
    row = {"id": id, "trackId": track, "eventType": event, "zoneId": zone, "severity": severity, "status": status,
           "createdAt": created, "predictedEntryS": None, "clipRef": clip, "ownerId": None, "ackedAt": None,
           "ackedVia": None, "escalationLevel": 0, "nextEscalationAt": None, "closedAt": None, "urgencyNote": None}
    stdb.t["alert"].append(row)
    stdb.log(id, "detected", f"{event} ({severity}) in zone {zone}", at=created)
    return row


@pytest.fixture
def stdb():
    s = FakeSpacetime()
    s.t["zone"].append({"id": "z_stairs", "roomId": "main", "name": "Stairs", "status": "active"})
    s.t["named_area"] += [{"id": "na_gate", "roomId": "main", "name": "Kitchen gate"},
                          {"id": "na_shelf", "roomId": "main", "name": "Book shelf"}]
    s.t["worker_contacts"].append({"caregiverId": "c_bob", "phone": "+15550000002", "joinCode": "bob"})
    s.t["room"].append({"id": "main", "name": "Playroom"})
    s.t["caregiver"] += [{"id": "c_maria", "name": "Maria", "role": "primary"}, {"id": "c_bob", "name": "Bob", "role": "backup"}]
    s.roles = {"maria-token": {"role": "caregiver", "caregiverId": "c_maria"}, "vision-token": {"role": "vision", "caregiverId": None}}
    return s


@pytest.fixture
def settings():
    s = Settings()
    s.poll_s, s.call_retry_delays_s, s.keyframe_wait_s, s.closing_time = 0.01, (0.0,), 8.0, "18:00"
    s.calls_enabled, s.public_base_url, s.claude_enabled = False, "https://worker.example.test", False
    import tempfile
    s.watch_keys_file = tempfile.mktemp(prefix="watch-keys-", suffix=".json")           # never the real file
    return s


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


def fake_response(payload: str | None, stop_reason="end_turn"):
    content = [] if payload is None else [SimpleNamespace(type="text", text=payload)]
    return SimpleNamespace(stop_reason=stop_reason, content=content)
