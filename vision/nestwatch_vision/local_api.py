"""The vision service's local HTTP and WebSocket API. See CLUADE.md "Local endpoints (local network only)".

  GET  /snapshot/{camera_id}     latest frame, faces blurred, for calibration and zone drawing
  POST /calibrate/{camera_id}    {image_points, floor_points} -> new homography and its error (MATH.md 1.6)
  POST /tag-adult                {track_id, caregiver_id, caregiver_name} marks a tracked person as an adult
  GET  /clips/{event_id}         blurred H.264 clip of an event
  GET  /keyframes/{event_id}/{n} blurred key frame n of an event
  GET  /health                   cameras, frame rate, model, Spacetime connection, buzzers, alarm
  WS   /buzzer                   wrist buzzers

Requests from outside the private network are refused (a router port-forward must not expose this), and browsers may
only call it from pages served on the local network.
"""
from concurrent.futures import Future
from dataclasses import dataclass, field
import ipaddress
import logging
import os
import queue
import re
import threading
from typing import Any, Callable

import cv2
import numpy as np
from fastapi import Body, FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from .calibration import CalibrationError, calibrate
from .evidence import SAFE_REF

log = logging.getLogger("nestwatch.api")
LOCAL_ORIGIN = r"^https?://(localhost|127\.0\.0\.1|\[::1\]|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|[A-Za-z0-9-]+\.local)(:\d+)?$"


class Control:
    """Work the API needs done ON the camera loop's thread (the pipeline is not thread-safe). The loop runs it between frames."""

    def __init__(self):
        self._q: queue.Queue = queue.Queue()

    def submit(self, fn: Callable[[], Any], timeout: float = 3.0) -> Any:
        fut: Future = Future()
        self._q.put((fn, fut))
        return fut.result(timeout=timeout)          # raises TimeoutError if the camera loop is stuck

    def run_pending(self) -> None:
        while True:
            try:
                fn, fut = self._q.get_nowait()
            except queue.Empty:
                return
            try:
                fut.set_result(fn())
            except Exception as e:
                fut.set_exception(e)


@dataclass
class Latest:
    """The newest frame and everyone the pose model saw in it, shared with the API thread."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    frame: np.ndarray | None = None
    people: list = field(default_factory=list)
    t: float = 0.0

    def set(self, frame, people, t):
        with self.lock:
            self.frame, self.people, self.t = frame, people, t

    def get(self):
        with self.lock:
            return self.frame, self.people, self.t


@dataclass
class VisionContext:
    camera_id: str
    control: Control
    latest: Latest
    hub: Any                                        # BuzzerHub
    recorder: Any = None                            # EvidenceRecorder, or None when clips are off
    set_homography: Callable[[np.ndarray], None] | None = None   # runs on the camera loop via Control
    tag_adult: Callable[[int, str], bool] | None = None          # runs on the camera loop via Control
    report_tag: Callable[[str, str], None] | None = None          # tells Spacetime (vision role)
    health: Callable[[], dict] = lambda: {}


class PrivateNetworkOnly:
    """Plain ASGI middleware (covers WebSockets too): refuse any client that is not on a private or loopback address."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            host = (scope.get("client") or ("", 0))[0]
            try:
                ok = ipaddress.ip_address(host).is_private or ipaddress.ip_address(host).is_loopback
            except ValueError:
                ok = False
            if not ok:
                log.warning("refused request from %r: not on the local network", host)
                if scope["type"] == "http":
                    await send({"type": "http.response.start", "status": 403, "headers": [(b"content-type", b"text/plain")]})
                    await send({"type": "http.response.body", "body": b"local network only"})
                else:
                    await send({"type": "websocket.close", "code": 1008})
                return
        await self.app(scope, receive, send)


def _pairs(v, name: str) -> np.ndarray:
    try:
        a = np.asarray(v, dtype=float)
    except (TypeError, ValueError):
        raise HTTPException(422, f"{name} must be a list of [x, y] pairs")
    if a.ndim != 2 or a.shape[1] != 2 or not np.isfinite(a).all():
        raise HTTPException(422, f"{name} must be a list of [x, y] pairs")
    return a


def create_app(ctx: VisionContext) -> FastAPI:
    app = FastAPI(title="NestWatch vision service", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(CORSMiddleware, allow_origin_regex=LOCAL_ORIGIN, allow_methods=["GET", "POST"], allow_headers=["content-type"])

    def check_camera(camera_id: str):
        if camera_id != ctx.camera_id:
            raise HTTPException(404, f"no camera '{camera_id}' here (this computer runs '{ctx.camera_id}')")

    @app.get("/health")
    def health():
        return {"camera": ctx.camera_id, **ctx.health()}

    @app.get("/snapshot/{camera_id}")
    def snapshot(camera_id: str):
        check_camera(camera_id)
        if ctx.recorder is None:
            raise HTTPException(503, "snapshots need the face blur (clips are switched off); refusing to send an unblurred picture")
        frame, people, _ = ctx.latest.get()
        if frame is None:
            raise HTTPException(503, "no frame from the camera yet")
        try:
            safe = ctx.recorder.blurred_full(frame, people)
        except Exception:
            log.exception("snapshot blur failed")
            raise HTTPException(503, "could not blur the snapshot; not sending it")      # fail closed
        ok, buf = cv2.imencode(".jpg", safe, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.post("/calibrate/{camera_id}")
    def calibrate_camera(camera_id: str, body: dict = Body(...)):
        check_camera(camera_id)
        img, flr = _pairs(body.get("image_points"), "image_points"), _pairs(body.get("floor_points"), "floor_points")
        if len(img) != len(flr) or not 4 <= len(img) <= 20:
            raise HTTPException(422, "need the same number of camera and floor points, between 4 and 20")
        frame, _, _ = ctx.latest.get()
        if frame is not None:
            h, w = frame.shape[:2]
            if (img < 0).any() or (img[:, 0] > w).any() or (img[:, 1] > h).any():
                raise HTTPException(422, f"camera points must be inside the {w} x {h} picture")
        try:
            r = calibrate(img, flr)
        except CalibrationError as e:
            raise HTTPException(422, str(e))
        out = {"ok": r.ok, "homography": r.H.tolist(), "reprojection_error": r.rms_m, "per_point_m": r.per_point_m,
               "holdout_m": r.holdout_m, "bad_point": r.bad_point, "warnings": r.warnings}
        if not r.ok:
            return JSONResponse(out, status_code=422)                                     # not applied
        if ctx.set_homography:
            try:
                ctx.control.submit(lambda: ctx.set_homography(r.H))                      # takes effect on the next frame
            except TimeoutError:
                raise HTTPException(503, "the camera loop is busy; the calibration was not applied, try again")
        return out

    @app.post("/tag-adult")
    def tag_adult(body: dict = Body(...)):
        m = re.fullmatch(r"t?(\d+)", str(body.get("track_id", "")))
        name, caregiver = str(body.get("caregiver_name", "")).strip(), str(body.get("caregiver_id", "")).strip()
        if not m or not name or not caregiver:
            raise HTTPException(422, "need track_id (like t12), caregiver_id and caregiver_name")
        tid = int(m.group(1))
        try:
            found = ctx.control.submit(lambda: ctx.tag_adult(tid, name)) if ctx.tag_adult else False
        except TimeoutError:
            raise HTTPException(503, "the camera loop is busy; try again")
        if not found:
            raise HTTPException(404, f"nobody with track id t{tid} is being tracked right now")
        if ctx.report_tag:
            ctx.report_tag(f"t{tid}", caregiver)
        return {"ok": True, "track_id": f"t{tid}", "caregiver": name}

    def evidence_file(event_id: str, suffix: str) -> str:
        if ctx.recorder is None:
            raise HTTPException(404, "clips are switched off on this computer")
        if not SAFE_REF.match(event_id):
            raise HTTPException(404, "no such clip")                                     # also stops ../ tricks
        base = ctx.recorder.clips_dir if suffix == ".mp4" else ctx.recorder.keyframes_dir
        path = os.path.join(base, event_id + suffix)
        if not os.path.isfile(path):
            raise HTTPException(404, "no such clip (it may still be recording, or was deleted after the retention period)")
        return path

    @app.get("/clips/{event_id}")
    def clip(event_id: str):
        return FileResponse(evidence_file(event_id, ".mp4"), media_type="video/mp4")      # supports seeking (Range requests)

    @app.get("/keyframes/{event_id}/{n}")
    def keyframe(event_id: str, n: int):
        if not 1 <= n <= 9:
            raise HTTPException(404, "no such key frame")
        return FileResponse(evidence_file(event_id, f"_{n}.jpg"), media_type="image/jpeg")

    @app.websocket("/buzzer")
    async def buzzer(ws: WebSocket):
        await ctx.hub.handle(ws)

    return PrivateNetworkOnly(app)
