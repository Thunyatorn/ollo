"""The vision service: camera -> pose -> floor positions -> tracks -> alerts -> Spacetime.

  python -m nestwatch_vision.main 0                      # webcam
  python -m nestwatch_vision.main clip.mp4 --demo-map    # a video nobody calibrated: stretch the picture over the room
  python -m nestwatch_vision.main 0 --dry-run            # do everything except send to Spacetime
"""
import argparse
import itertools
import logging
import os
import re
import threading
import time
from datetime import datetime
import numpy as np
import uvicorn

from .alarm import AlarmPlayer
from .buzzers import BuzzerHub
from .calibration import demo_homography
from .coordinator import AlertCoordinator
from .local_api import Control, Latest, VisionContext, create_app
from .capture import open_source
from .config import EvidenceConfig, PipelineConfig, PoseConfig
from .evidence import EvidenceRecorder
from .uploader import KeyframeUploader
from .pipeline import Pipeline
from .pose import PoseModel
from .sync import SpacetimeHttp, SpacetimeSink
from .zones import ZoneCache

log = logging.getLogger("nestwatch")


class ZoneRefresher(threading.Thread):
    """Re-reads the zones every second so a rule confirmed on the dashboard takes effect without a restart."""

    def __init__(self, client: SpacetimeHttp, cache: ZoneCache, room_id: str, every: float = 1.0):
        super().__init__(daemon=True, name="zones")
        self.client, self.cache, self.room_id, self.every = client, cache, room_id, every
        self._stop_evt = threading.Event()

    def run(self) -> None:
        while not self._stop_evt.is_set():
            try:
                rows = [z for z in self.client.zones() if z["room_id"] == self.room_id]
                self.cache.load(rows)                      # replaces the list in one assignment, safe to read from the main loop
            except Exception as e:
                log.warning("could not refresh zones: %s", e)
            self._stop_evt.wait(self.every)

    def stop(self) -> None:
        self._stop_evt.set()


class AlertPoller(threading.Thread):
    """Reads the live alerts (twice a second) and the caregiver roster (every 5 s), and hands them to the coordinator,
    which decides buzzes, stops and the local alarm."""
    ALERTS = ("SELECT id, status, severity, owner_id, escalation_level FROM alert "
              "WHERE status = 'notified' OR status = 'escalated' OR status = 'unanswered' OR status = 'owned'")

    def __init__(self, client: SpacetimeHttp, coordinator: AlertCoordinator, every: float = 0.5):
        super().__init__(daemon=True, name="alerts")
        self.client, self.coord, self.every = client, coordinator, every
        self._stop_evt = threading.Event()
        self.caregivers: list[dict] = []
        self.ok = False

    def run(self) -> None:
        last_roster = 0.0
        while not self._stop_evt.is_set():
            try:
                if time.monotonic() - last_roster > 5.0:
                    self.caregivers = self.client.sql("SELECT id, name, role, buzzer_id, on_duty FROM caregiver")
                    last_roster = time.monotonic()
                self.coord.tick(self.client.sql(self.ALERTS), self.caregivers)
                if not self.ok:
                    log.info("watching alerts")
                self.ok = True
            except Exception as e:
                if self.ok:
                    log.warning("cannot read alerts from Spacetime: %s", e)
                self.ok = False
            self._stop_evt.wait(self.every)

    def stop(self) -> None:
        self._stop_evt.set()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--uri", default="http://127.0.0.1:3000")
    ap.add_argument("--db", default="nestwatch-test")
    ap.add_argument("--token-file", default="../tools/.vision-token")
    ap.add_argument("--room", default="main")
    ap.add_argument("--camera", default="cam1")
    ap.add_argument("--weights", default=PoseConfig().weights)
    ap.add_argument("--demo-map", action="store_true", help="no calibration: stretch the whole picture over the room")
    ap.add_argument("--dry-run", action="store_true", help="do not send anything to Spacetime")
    ap.add_argument("--realtime", action="store_true", help="play a video file at its own speed")
    ap.add_argument("--no-evidence", action="store_true", help="do not save clips (otherwise blurred clips go under evidence/)")
    ap.add_argument("--evidence-dir", default=EvidenceConfig().dir)
    ap.add_argument("--host", default="127.0.0.1", help="where the local API listens; 0.0.0.0 lets other devices on the daycare network reach it")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-api", action="store_true", help="no local API, buzzers or alarm")
    ap.add_argument("--quiet-alarm", action="store_true", help="log the local alarm instead of playing it (for testing)")
    ap.add_argument("--max-seconds", type=float, default=0)
    ap.add_argument("--worker-url", default=os.environ.get("WORKER_URL", ""), help="send blurred key frames of each event here (e.g. http://127.0.0.1:8787)")
    ap.add_argument("--nap-time", default="12:30-14:30", help="local time window of the 'nap_time' schedule that rules can use")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    token = open(a.token_file).read().strip()
    client = SpacetimeHttp(a.uri, a.db, token)
    room = client.room(a.room)
    if room is None:
        raise SystemExit(f"room '{a.room}' does not exist; create it in Setup or run scripts/seed-local.sh")
    cam = client.camera(a.camera)
    H = np.array(cam["homography"]).reshape(3, 3) if cam and len(cam["homography"]) == 9 else None

    src = open_source(a.source, realtime=a.realtime)
    if hasattr(src, "start"):
        src.start()
    frames = src.frames()
    first = next(frames, None)
    if first is None:
        raise SystemExit("no frames from the camera")
    if H is None and a.demo_map:
        h, w = first.image.shape[:2]
        H = demo_homography(w, h, room["width_m"], room["height_m"])
        log.warning("DEMO MAP: the picture is stretched over the room, positions are not real")
    if H is None:
        log.error("camera '%s' is not calibrated: positions will not be sent. Run scripts/calibrate.py (or pass --demo-map)", a.camera)

    nap = re.fullmatch(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", a.nap_time)
    if not nap:
        raise SystemExit("--nap-time must look like 12:30-14:30")
    h1, m1, h2, m2 = map(int, nap.groups())
    zones = ZoneCache(named_schedules={"nap_time": (h1 * 60 + m1, h2 * 60 + m2)})
    pipeline = Pipeline(room["width_m"], room["height_m"], H, zones, PipelineConfig())
    refresher = ZoneRefresher(client, zones, a.room)
    refresher.start()
    sink = None if a.dry_run else SpacetimeSink(client)
    pose = PoseModel(PoseConfig(weights=a.weights))
    uploader = KeyframeUploader(a.worker_url, token) if a.worker_url and not a.dry_run else None
    recorder = None if a.no_evidence else EvidenceRecorder(EvidenceConfig(dir=a.evidence_dir), on_written=uploader)   # raises if the face detector model is missing: no recording without it
    log.info("room '%s' %.1f x %.1f m, pose model on %s, %s", a.room, room["width_m"], room["height_m"], pose.device, "dry run" if a.dry_run else "sending to Spacetime")

    # ---- local API, buzzers and the local alarm ----------------------------------------------------------
    stats = {"frames": 0, "fps": 0.0, "people": 0, "tracks": 0}
    control, latest = Control(), Latest()
    hub = BuzzerHub()
    alarm = AlarmPlayer(play_once=(lambda: (log.warning("ALARM (quiet mode)"), time.sleep(2.0))) if a.quiet_alarm else None)

    def acknowledge(alert_id: str, caregiver_id: str) -> None:
        log.info("buzzer tap: %s acknowledges %s", caregiver_id, alert_id)
        if sink:
            sink.reducer("acknowledge_alert", [alert_id, caregiver_id, "buzzer"])
    coord = AlertCoordinator(hub, alarm, acknowledge)
    hub.on_ack = coord.on_buzzer_ack
    poller = AlertPoller(client, coord)
    server = None
    if not a.no_api:
        poller.start()
        ctx = VisionContext(
            a.camera, control, latest, hub, recorder,
            set_homography=pipeline.set_homography, tag_adult=pipeline.tag_adult,
            report_tag=(lambda track, cg: sink.reducer("tag_adult", [track, cg])) if sink else None,
            health=lambda: {
                **stats, "camera_online": getattr(src, "online", True), "calibrated": pipeline.H is not None,
                "detector": f"pose on {pose.device}", "spacetime_online": (sink.online if sink else None), "alerts_watched": poller.ok,
                "buzzers": {b: {"battery": i.get("battery"), "seconds_since_seen": round(time.monotonic() - i["last_seen"], 1)}
                            for b, i in hub.info.items() if b in hub.connected()},
                "alarm": {"active": alarm.active, "reasons": alarm.reasons()},
                "evidence": None if recorder is None else {"buffered_frames": recorder.buffered_frames, "dropped_unblurred": recorder.dropped_unblurred},
                "keyframes_to_worker": None if uploader is None else {"sent": uploader.sent, "failed": uploader.failed},
            })
        server = uvicorn.Server(uvicorn.Config(create_app(ctx), host=a.host, port=a.port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True, name="api").start()
        log.info("local API on http://%s:%d (snapshot, calibrate, tag-adult, clips, health, buzzer)", a.host, a.port)

    last_pos = last_health = last_log = last_clean = start = time.perf_counter()
    n = 0
    try:
        for f in itertools.chain([first], frames):          # not [first, *frames]: that would read a whole video, or wait forever on a camera
            control.run_pending()                                                  # calibrations and adult tags from the API
            everyone = pose.infer_all(f.image)                                     # includes low-confidence people, for blurring
            people = [p for p in everyone if p.box_conf >= pose.cfg.conf]          # tracking uses only the confident ones
            if recorder:
                recorder.add(f.image, f.t, everyone)                              # blurred before anything is kept
            res = pipeline.step(people, f.t, datetime.now(), everyone)
            latest.set(f.image, everyone, f.t)
            n += 1
            now = time.perf_counter()
            stats.update(frames=n, fps=round(n / max(now - start, 1e-6), 1), people=len(people), tracks=len(res.tracks))
            if sink and res.positions and now - last_pos >= 0.1:            # about 8 to 10 position updates a second (spec)
                sink.positions(a.room, res.positions)
                last_pos = now
            for e in res.events:
                log.warning("ALERT %s %s %s predicted %s s", e.track_id, e.event_type, e.zone_id, e.predicted_entry_s)
                coord.on_local_event(e.clip_ref, e.severity, bool(sink and sink.online))     # no Spacetime: sound the alarm here
                if recorder:
                    recorder.trigger(e.clip_ref, f.t)
                if sink:
                    sink.event(e.track_id, e.event_type, e.zone_id, e.severity, e.predicted_entry_s, e.clip_ref)
            if recorder:
                recorder.tick(f.t)
                if now - last_clean >= 3600:
                    recorder.cleanup()
                    last_clean = now
            if sink and now - last_health >= 10:
                sink.health(a.camera, "online" if getattr(src, "online", True) else "offline")
                last_health = now
            if now - last_log >= 5:
                log.info("%d frames, %.1f fps, %d people, %d tracks%s", n, n / (now - start), len(people), len(res.tracks),
                         f", {sink.pending()} events waiting" if sink and sink.pending() else "")
                last_log = now
            if a.max_seconds and now - start >= a.max_seconds:
                break
    except KeyboardInterrupt:
        pass
    finally:
        src.stop()
        refresher.stop()
        poller.stop()
        if server:
            server.should_exit = True
        alarm.close()
        if recorder:
            recorder.wait(15.0)
            if recorder.dropped_unblurred:
                log.warning("%d frames were dropped because blurring failed", recorder.dropped_unblurred)
            recorder.stop()
        if sink:
            sink.flush(2.0)
            sink.stop()
    log.info("done: %d frames in %.1f s", n, time.perf_counter() - start)


if __name__ == "__main__":
    main()
