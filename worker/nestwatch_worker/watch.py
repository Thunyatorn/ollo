"""Garmin watches as wrist buzzers (the ollo Connect IQ app in garmin/).

A watch has no Spacetime sign-in, so a signed-in caregiver pairs it: the dashboard asks for a pairing code (POST
/watch/pair), the caregiver types it into the app's settings in the Garmin Connect phone app, and from then on the watch
sends it with every request. Only the code's SHA-256 is stored (in a git-ignored file), a new pairing replaces the old
one, and too many wrong codes in a short time slow everyone down. The watch reaches the worker through the Garmin Connect
phone app, so it needs the worker's public https address (PUBLIC_BASE_URL).

  GET  /watch/state   open alerts for the paired caregiver, most urgent first, and whether to buzz
  POST /watch/act     {alert_id, decision: acknowledge | decline}: "I'm on it" or "I can't respond", via watch
"""
import hashlib
import json
import os
import secrets
import threading
import time

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"            # no 0/O, 1/I/L: the code is typed on a phone
SHORT = {
    "zone_entry_predicted": "Heading into", "zone_entry": "In", "fall": "Possible fall", "unsupervised": "No adult near",
    "child_not_visible": "Out of sight", "possible_distress": "Hands at throat", "rhythmic_movement": "Shaking",
    "stillness": "Not moving", "climbing": "Climbing", "head_count_mismatch": "Head count",
}
RANK = {"high": 0, "medium": 1, "low": 2}
WAITING = ("notified", "escalated", "unanswered")
NEXT = {0: "Backup is called", 1: "Alarm and all staff", 2: None}


def normalize(code: str) -> str:
    return "".join(ch for ch in str(code).upper() if ch in ALPHABET)


class WatchKeys:
    """Pairing codes: sha256(code) -> caregiver id, kept in a JSON file next to the worker token."""

    def __init__(self, path: str, max_failures_per_minute: int = 20, clock=time.time):
        self.path, self.max_failures, self.clock = path, max_failures_per_minute, clock
        self._lock = threading.Lock()
        self._failures: list[float] = []
        try:
            with open(path) as f:
                self._keys: dict = json.load(f)
        except (OSError, ValueError):
            self._keys = {}

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(self._keys, f)
        os.replace(tmp, self.path)

    def pair(self, caregiver_id: str) -> str:
        """A new code for this caregiver; any earlier code of theirs stops working."""
        code = "".join(secrets.choice(ALPHABET) for _ in range(10))
        with self._lock:
            self._keys = {h: v for h, v in self._keys.items() if v["caregiver"] != caregiver_id}
            self._keys[hashlib.sha256(code.encode()).hexdigest()] = {"caregiver": caregiver_id, "since": self.clock()}
            self._save()
        return f"{code[:5]}-{code[5:]}"

    def throttled(self) -> bool:
        now = self.clock()
        with self._lock:
            self._failures = [t for t in self._failures if now - t < 60]
            return len(self._failures) >= self.max_failures

    def who(self, code: str) -> str | None:
        """The caregiver a code belongs to, or None (and the failure is counted)."""
        rec = self._keys.get(hashlib.sha256(normalize(code).encode()).hexdigest()) if code else None
        if rec is None:
            with self._lock:
                self._failures.append(self.clock())
            return None
        return rec["caregiver"]


def watch_state(me: dict, alerts: list[dict], zones: dict, labels: dict, names: dict, now: float, limit: int = 5) -> dict:
    """What the watch shows: small, because a watch app has little memory. `me` is the caregiver row."""
    open_ = [a for a in alerts if a["status"] in WAITING or a["status"] == "owned"]
    open_.sort(key=lambda a: (a["status"] not in WAITING, RANK.get(a["severity"], 3), a["createdAt"]))
    out = []
    for a in open_[:limit]:
        nxt = a.get("nextEscalationAt")
        out.append({
            "id": a["id"], "sev": a["severity"], "what": SHORT.get(a["eventType"], a["eventType"]),
            "where": zones.get(a["zoneId"], ""), "child": labels.get(a["trackId"], a["trackId"].lstrip("t")),
            "waiting": a["status"] in WAITING, "status": a["status"],
            "owner": None if not a.get("ownerId") else ("you" if a["ownerId"] == me["id"] else names.get(a["ownerId"], "someone")),
            "next_in": None if not nxt or a["status"] not in WAITING else max(0, int(nxt - now)),
            "next": NEXT.get(a.get("escalationLevel", 0)) if a["status"] in WAITING else None,
        })
    waiting = [x for x in out if x["waiting"]]
    return {"me": me["name"], "count": sum(1 for a in open_ if a["status"] in WAITING), "alerts": out,
            "buzz": waiting[0]["sev"] if waiting and waiting[0]["sev"] in ("high", "medium") else None}
