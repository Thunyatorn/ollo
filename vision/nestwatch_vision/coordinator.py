"""Turns the alert table into buzzes, stops and the local alarm. The rules come from CLUADE.md:

  * a new high or medium alert buzzes the on-duty PRIMARY caregiver's wrist buzzer (low alerts are app-only)
  * escalated: the backup's buzzer too (they are also being phoned)
  * unanswered (second timeout): every on-duty buzzer, and the loud local alarm
  * as soon as someone owns the alert (or it closes): "stop" to every buzzer that was buzzed, alarm off
  * a tap on a buzzer acknowledges the alert as that buzzer's caregiver
  * a HIGH alert raised while Spacetime is unreachable sounds the local alarm at once (nobody else can be told)
"""
import logging
from typing import Callable

log = logging.getLogger("nestwatch.coordinator")
OPEN = ("notified", "escalated", "unanswered")
DONE = ("owned", "closed", "reported")
OFFLINE_ALARM_S = 30.0


class AlertCoordinator:
    def __init__(self, hub, alarm, ack: Callable[[str, str], None]):
        """hub: has send(buzzer_id, msg) and broadcast(msg). alarm: has start(reason, duration_s) and stop(reason).
        ack(alert_id, caregiver_id) records the acknowledgement in Spacetime (via buzzer)."""
        self.hub, self.alarm, self._ack = hub, alarm, ack
        self.caregivers: list[dict] = []
        self.buzzed: dict[str, set] = {}          # alert id -> (buzzer id, connection number) already sent a buzz
        self.stopped: set = set()                 # alert ids already told to stop
        self.owner_names: dict[str, str] = {}

    # ---- the polling loop calls this with fresh rows --------------------------------------------------
    def tick(self, alerts: list[dict], caregivers: list[dict]) -> None:
        self.caregivers = caregivers
        by_id = {c["id"]: c for c in caregivers}
        live = set()
        for a in alerts:
            aid, status, owner = a["id"], a["status"], a.get("owner_id")
            live.add(aid)
            if status in OPEN and not owner:
                if a["severity"] in ("high", "medium"):                      # low is app-only
                    gen = getattr(self.hub, "generation", lambda b: 0)
                    for buzzer in self._targets(status):
                        key = (buzzer, gen(buzzer))               # a buzzer that reconnected is a new connection: tell it again
                        if key not in self.buzzed.setdefault(aid, set()):
                            if self.hub.send(buzzer, {"type": "buzz", "alert_id": aid, "severity": a["severity"]}):
                                self.buzzed[aid].add(key)
                if status == "unanswered":
                    self.alarm.start(f"unanswered:{aid}")
                else:
                    self.alarm.stop(f"unanswered:{aid}")
            elif aid in self.buzzed and aid not in self.stopped and (status in DONE or owner):
                who = by_id.get(owner, {}).get("name", "someone")
                self.hub.broadcast({"type": "stop", "alert_id": aid, "owner": who})
                self.stopped.add(aid)
                self.alarm.stop(f"unanswered:{aid}")
            if status in DONE or owner:
                self.alarm.stop(f"unanswered:{aid}")
        for gone in [k for k in self.buzzed if k not in live]:                # left the live set between two polls (taken and closed)
            if gone not in self.stopped:
                self.hub.broadcast({"type": "stop", "alert_id": gone, "owner": "someone"})   # never leave a wrist vibrating
            self.buzzed.pop(gone, None); self.stopped.discard(gone)
            self.alarm.stop(f"unanswered:{gone}")

    def _targets(self, status: str) -> list[str]:
        on = [c for c in self.caregivers if c.get("on_duty") and c.get("buzzer_id")]
        if status == "notified":
            chosen = [c for c in on if c["role"] == "primary"]
        elif status == "escalated":
            chosen = [c for c in on if c["role"] in ("primary", "backup")]
        else:
            chosen = on
        return [c["buzzer_id"] for c in chosen]

    # ---- events -----------------------------------------------------------------------------------------
    def on_buzzer_ack(self, buzzer_id: str, alert_id: str) -> bool:
        """A caregiver tapped their buzzer. The connection tells us which buzzer; the roster tells us whose it is."""
        who = next((c for c in self.caregivers if c.get("buzzer_id") == buzzer_id), None)
        if who is None or not alert_id:
            log.warning("ignoring ack from buzzer %r for alert %r: not paired with a caregiver", buzzer_id, alert_id)
            return False
        self._ack(alert_id, who["id"])
        return True

    def on_local_event(self, event_id: str, severity: str, spacetime_online: bool) -> None:
        """The vision service just raised an event. If Spacetime cannot be reached and it is high, sound the alarm ourselves."""
        if severity == "high" and not spacetime_online:
            self.alarm.start(f"offline:{event_id}", OFFLINE_ALARM_S)
