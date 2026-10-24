"""Controlled staged-demo vision, not a pediatric or medical detector.

Primary detector: local YOLO pose (17 COCO keypoints) with ByteTrack IDs, run
on CPU so no frame leaves the machine. Fallback: OpenCV's bundled HOG people
model, which is weak on small, seated, crawling, and occluded people. Never
infer age or scene safety. The optional Claude second opinion (review.py) runs
only after a local alert and receives face-blurred crops of the flagged person.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import math
import os
import struct
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from .events import EventDetector
from .predict import ApproachMonitor, Calibration
from .rules import active_zones
from .review import REVIEW_KINDS, ReviewResult, VisibleObservation, crop_frames, second_opinion  # noqa: F401 (re-exported)
from .store import KINDS

MAX_JPEG_BYTES = 1_500_000
MAX_PIXELS = 2_000_000
MODELS_DIR = Path(os.getenv('MODELS_DIR', str(Path(__file__).resolve().parent.parent / 'models')))
POSE_MODEL = os.getenv('POSE_MODEL', 'yolo26n-pose.pt')
# 3 CPU threads: ~35 ms per frame using ~1.2 cores at 12 fps, versus ~30 ms using ~2.7 cores with
# Ultralytics' default of 8. Applied after predictor setup, which resets the thread count.
POSE_THREADS = int(os.getenv('POSE_THREADS', '3'))
TRACK_TIMEOUT_MS = 1500
LEFT_ANKLE, RIGHT_ANKLE = 15, 16


def foot_point(person: dict) -> tuple[float, float] | None:
    """Ground contact: x from confident ankles (else the box center), y from the box bottom where soles meet the floor.

    Ankle joints sit ~4–5% of body height above the floor, which the evaluation showed can put a
    person just outside a zone inside it. When the box is cut off by the frame's bottom edge, the
    ankles give y; with no ankles either, the ground position is unknown, never "outside".
    """
    ankles = [kp for kp in (person.get('keypoints') or [])[LEFT_ANKLE:RIGHT_ANKLE + 1] if kp[2] >= 0.5]
    bottom = person['y'] + person['height']
    x = sum(a[0] for a in ankles) / len(ankles) if ankles else person['x'] + person['width'] / 2
    if bottom < 0.98:
        return x, bottom
    return (x, max(a[1] for a in ankles)) if ankles else None


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Read dimensions before OpenCV allocation; reject malformed/oversized JPEGs."""
    if len(data) > MAX_JPEG_BYTES or not data.startswith(b'\xff\xd8'):
        raise ValueError('Expected a bounded JPEG image')
    offset = 2
    while offset < len(data):
        if data[offset] != 0xFF:
            raise ValueError('Malformed JPEG marker')
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack('>H', data[offset:offset + 2])[0]
        if length < 2 or offset + length > len(data):
            raise ValueError('Malformed JPEG segment')
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            if length < 8:
                raise ValueError('Malformed JPEG dimensions')
            height, width = struct.unpack('>HH', data[offset + 3:offset + 7])
            if width < 32 or height < 32 or width * height > MAX_PIXELS or max(width, height) > 2048:
                raise ValueError('JPEG dimensions exceed limits')
            return width, height
        if marker == 0xDA:
            break
        offset += length
    raise ValueError('JPEG dimensions missing')


def valid_polygon(vertices) -> list[tuple[float, float]]:
    if not isinstance(vertices, (list, tuple)) or not 3 <= len(vertices) <= 16:
        return []
    try:
        result = [(float(v[0]), float(v[1])) for v in vertices if len(v) == 2]
    except (TypeError, ValueError, IndexError):
        return []
    if len(result) != len(vertices) or any(not math.isfinite(x) or not math.isfinite(y) or not 0 <= x <= 1 or not 0 <= y <= 1 for x, y in result):
        return []
    area = abs(sum(result[i][0] * result[(i + 1) % len(result)][1] - result[(i + 1) % len(result)][0] * result[i][1] for i in range(len(result)))) / 2
    return result if area > 0.0001 else []


def point_in_polygon(point, vertices) -> bool:
    """Even/odd polygon test, including the boundary."""
    x, y = point
    inside = False
    for i, (ax, ay) in enumerate(vertices):
        bx, by = vertices[(i + 1) % len(vertices)]
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) < 1e-9 and min(ax, bx) - 1e-9 <= x <= max(ax, bx) + 1e-9 and min(ay, by) - 1e-9 <= y <= max(ay, by) + 1e-9:
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


class ZoneTracker:
    """Three observed positions confirm a state; missing data is never 'outside'."""
    def __init__(self):
        self.state = None
        self.pending = None
        self.count = 0

    def update(self, inside: bool | None) -> str | None:
        if inside is None:
            self.pending, self.count = None, 0
            return None
        if inside == self.pending:
            self.count += 1
        else:
            self.pending, self.count = inside, 1
        if self.count < 3 or self.state == inside:
            return None
        previous = self.state
        self.state = inside
        if inside:
            return 'present' if previous is None else 'entered'
        return None


class VisionEngine:
    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}
        self._lock = threading.Lock()
        self._hog = None
        self._pose = None
        self.detector = 'pending'
        self.frame_aspect = 16 / 9
        self._task = None
        self._client = None
        self.on_review = None  # Set by the API to attach results immediately, even if no further frame arrives.
        self.clock = datetime.now  # Local time for rule schedules; replaceable in tests.
        self._generation = 0
        self.reset()

    def configure(self, settings: dict):
        self.settings = dict(settings)
        self.reset()

    def reset(self, session_id=None, epoch=None):
        self._generation += 1
        if self._task is not None:
            self._task.cancel()
        self._task = None
        self.session_id, self.epoch = session_id, epoch
        self.last_seq = -1
        self.last_media_time = -1
        self.last_receipt = None
        self.frames = deque(maxlen=32)
        self.zone = ZoneTracker()
        self._polygon = []
        self.track_box = None
        self.track_seen = -1
        self.zones = {}  # (track ID, zone ID) → ZoneTracker
        self.active = []  # Restricted zones in force: default zone plus confirmed, in-schedule rules.
        self._zone_signature = None
        self.tracks_seen = {}
        self._tracker_fresh = True
        self.events = EventDetector(self.settings)
        self.approach = ApproachMonitor()
        try:
            self.calibration = Calibration.from_dict(self.settings['calibration']) if isinstance(self.settings.get('calibration'), dict) else None
        except (KeyError, TypeError, ValueError, ArithmeticError):
            self.calibration = None
        self.processed_at = deque(maxlen=36)
        self.cloud = {'requests': 0, 'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0, 'cost_known': True}
        self._pending = None
        self.review_status = 'disabled'
        self.tracking_status = 'waiting'
        self.last_review = None

    def _load_pose(self):
        """Weights come from `npm run models`; runtime never downloads."""
        if os.getenv('LOOKOUT_DETECTOR', 'pose') == 'hog' or self._pose is False:
            return None
        if self._pose is None:
            try:
                from ultralytics import YOLO
                path = MODELS_DIR / POSE_MODEL
                self._pose = YOLO(str(path), task='pose') if path.is_file() else False
            except Exception:
                self._pose = False
        return self._pose or None

    def warm(self):
        """Load weights and run one untracked inference so the first live frame is not slow."""
        with self._lock:
            model = self._load_pose()
            if model is not None:
                import numpy as np
                model.predict(np.zeros((360, 640, 3), dtype=np.uint8), imgsz=640, verbose=False)
                self._limit_threads()
                self.detector = 'pose'

    def _limit_threads(self):
        import torch
        if torch.get_num_threads() != POSE_THREADS:
            torch.set_num_threads(POSE_THREADS)

    def _pose_people(self, model, image):
        # Restart ByteTrack IDs after a reset; otherwise keep identities across frames.
        persist, self._tracker_fresh = not self._tracker_fresh, False
        result = model.track(image, persist=persist, tracker='bytetrack.yaml', classes=[0], conf=0.35, imgsz=640, verbose=False)[0]
        self._limit_threads()
        if result.boxes is None or not len(result.boxes):
            return []
        boxes, confs = result.boxes.xyxyn.tolist(), result.boxes.conf.tolist()
        ids = result.boxes.id.int().tolist() if result.boxes.id is not None else [None] * len(boxes)
        points = result.keypoints.xyn.tolist() if result.keypoints is not None else [[]] * len(boxes)
        point_conf = result.keypoints.conf.tolist() if result.keypoints is not None and result.keypoints.conf is not None else [[1.0] * len(p) for p in points]
        return [{'x': x1, 'y': y1, 'width': x2 - x1, 'height': y2 - y1, 'confidence': round(c, 3), 'track_id': tid,
                 'keypoints': [[round(px, 4), round(py, 4), round(pc, 3)] for (px, py), pc in zip(kp, kc)]}
                for (x1, y1, x2, y2), c, tid, kp, kc in zip(boxes, confs, ids, points, point_conf)]

    def _detect(self, jpeg):
        width, height = jpeg_dimensions(jpeg)
        try:
            import cv2
            import numpy as np
        except ImportError:
            return [], 'unavailable'
        with self._lock:
            image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.shape[1] != width or image.shape[0] != height:
                raise ValueError('JPEG decoding failed')
            scale = min(1.0, 640 / width)
            if scale < 1:
                image = cv2.resize(image, (int(width * scale), int(height * scale)))
            self.frame_aspect = image.shape[1] / image.shape[0]
            model = self._load_pose()
            if model is not None:
                self.detector = 'pose'
                return self._pose_people(model, image), 'active'
            self.detector = 'hog'
            if not hasattr(cv2, 'HOGDescriptor'):
                return [], 'unavailable'
            if self._hog is None:
                self._hog = cv2.HOGDescriptor()
                self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
            h, w = image.shape[:2]
            if w < 64 or h < 128:
                return [], 'limited'
            boxes, _ = self._hog.detectMultiScale(image, winStride=(8, 8), padding=(8, 8), scale=1.08)
            normalized = [{'x': float(x) / w, 'y': float(y) / h, 'width': float(bw) / w, 'height': float(bh) / h} for x, y, bw, bh in boxes]
            return normalized, 'active'

    def _settings_polygon(self):
        zone = self.settings.get('zone', {})
        vertices = zone.get('vertices', self.settings.get('polygon', [])) if isinstance(zone, dict) else []
        return [] if isinstance(zone, dict) and not zone.get('enabled', True) else valid_polygon(vertices)

    def _refresh_zones(self):
        """Recompute zones in force (rule schedules change with the clock); keep state for zones that remain."""
        zones = [z for z in active_zones(self.settings, self.clock()) if valid_polygon([list(v) for v in z['polygon']])]
        signature = tuple((z['id'], tuple(z['polygon'])) for z in zones)
        if signature == self._zone_signature:
            return
        ids = {z['id'] for z in zones}
        self.zones = {key: tracker for key, tracker in self.zones.items() if key[1] in ids}
        for z in zones:
            z['floor'] = self.calibration.zone_to_floor(z['polygon']) if self.calibration else None
        self.active, self._zone_signature = zones, signature

    def _predictive_status(self) -> str:
        if self.calibration is None:
            return 'needs calibration'
        return 'active' if active_zones(self.settings, self.clock()) else 'no zone'

    def _update_tracks(self, people, media_time, epoch, seq):
        """Per-person, per-zone entry hysteresis; unseen IDs report missing data, never 'outside'."""
        overlays, observations, seen = [], [], set()
        for person in people:
            tid = person['track_id']
            seen.add(tid)
            self.tracks_seen[tid] = media_time
            foot = foot_point(person)
            inside_any, best = False if foot else None, None
            for zone in self.active:
                inside = point_in_polygon(foot, zone['polygon']) if foot else None
                inside_any = inside_any or inside
                event = self.zones.setdefault((tid, zone['id']), ZoneTracker()).update(inside)
                if event:
                    where = zone['name'] if zone['id'] == 'default' else f"{zone['name']} (restricted by rule)"
                    text = f'Tracked person {tid} entered {where}.' if event == 'entered' else f'Person {tid} present in {where}; crossing was not observed.'
                    observations.append({'kind': 'boundary', 'observations': [text], 'origin': 'local_rule', 'priority': zone['priority'], 'track_id': f'person-{tid}', 'zone_id': zone['id'], 'frame_seq': seq, 'media_time_ms': media_time})
                if zone['floor'] is None:
                    continue
                approach = self.approach.update((tid, zone['id']), foot, media_time / 1000, self.calibration, zone['floor'])
                if best is None or approach['p'] > best['p']:
                    best = {**approach, 'zone': zone['name']}
                if approach['started']:
                    eta = f"about {approach['eta_s']:g} s" if approach['eta_s'] is not None else 'within 3 s'
                    target = 'the restricted area' if zone['id'] == 'default' else zone['name']
                    observations.append({'kind': 'approach', 'observations': [f"Person {tid} is heading for {target}: {eta} away at the current pace ({approach['p']:.0%} of predicted paths)."], 'origin': 'local_rule', 'priority': 'medium', 'track_id': f'person-{tid}', 'zone_id': zone['id'], 'frame_seq': seq, 'media_time_ms': media_time})
            floor = self.calibration.to_floor(foot) if self.calibration is not None and foot else None
            overlays.append({**person, 'id': f'person-{tid}', 'label': f'Person {tid} · pose tracking', 'foot': [round(foot[0], 4), round(foot[1], 4)] if foot else None, 'floor': [round(float(c), 3) for c in floor] if floor is not None else None, 'in_zone': inside_any, 'approach': best, 'epoch': epoch, 'frame_seq': seq, 'media_time_ms': media_time})
            if person.get('keypoints'):
                for detected in self.events.update(tid, person, media_time, self.frame_aspect):
                    observations.append({'kind': detected['kind'], 'observations': [f"Person {tid}: {detected['text']}"], 'origin': 'local_rule', 'priority': detected['priority'], 'track_id': f'person-{tid}', 'frame_seq': seq, 'media_time_ms': media_time})
        for tid in list(self.tracks_seen):
            if tid in seen:
                continue
            keys = [key for key in self.zones if key[0] == tid]
            if media_time - self.tracks_seen[tid] > TRACK_TIMEOUT_MS:
                for key in keys:
                    self.zones.pop(key)
                self.approach.forget(tid)
                self.tracks_seen.pop(tid)
                self.events.forget(tid)
            else:
                for key in keys:
                    self.zones[key].update(None)
        return overlays, observations

    def _choose_track(self, boxes, media_time):
        if not boxes:
            if media_time - self.track_seen > 1500:
                self.track_box = None
                self.zone = ZoneTracker()
            self.zone.update(None)
            return None
        center = lambda b: (b['x'] + b['width'] / 2, b['y'] + b['height'] / 2)
        if self.track_box is None:
            box = max(boxes, key=lambda b: b['width'] * b['height'])
        else:
            cx, cy = center(self.track_box)
            box = min(boxes, key=lambda b: math.dist(center(b), (cx, cy)))
            if math.dist(center(box), (cx, cy)) > .30:
                self.zone.update(None)
                if media_time - self.track_seen > 1500:
                    self.track_box = None
                    self.zone = ZoneTracker()
                return None
        self.track_box = box
        self.track_seen = media_time
        return box

    async def process_frame(self, frame: dict) -> dict:
        """One caller at a time. Backend should use a bounded latest-frame queue."""
        observations = []
        sid = str(frame.get('session_id', ''))
        epoch, seq = int(frame.get('epoch', 0)), int(frame.get('frame_seq', 0))
        media_time = float(frame.get('media_time_ms', 0))
        if not math.isfinite(media_time) or media_time < 0:
            raise ValueError('Invalid frame time')
        if self.session_id is None:
            self.session_id, self.epoch = sid, epoch
        if sid != self.session_id or epoch != self.epoch:
            # Backend reset/start owns epochs: late frames cannot silently change one.
            return self._result([], [], rejected='wrong_epoch')
        if seq <= self.last_seq or media_time < self.last_media_time:
            return self._result([], [], rejected='out_of_order')
        encoded = frame.get('image', '')
        if not isinstance(encoded, str) or len(encoded) > 2_100_000:
            raise ValueError('Frame payload too large')
        if encoded.startswith('data:image/jpeg;base64,'):
            encoded = encoded.split(',', 1)[1]
        try:
            jpeg = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Invalid base64 JPEG') from exc
        jpeg_dimensions(jpeg)
        generation = self._generation
        boxes, status = await asyncio.to_thread(self._detect, jpeg)
        if generation != self._generation:
            return self._result([], [], rejected='expired_processing')
        self.last_seq, self.last_media_time = seq, media_time
        self.last_receipt = time.monotonic()
        self.processed_at.append(self.last_receipt)
        self.tracking_status = status
        self.frames.append({'frame_seq': seq, 'media_time_ms': media_time, 'jpeg': jpeg, 'people': {b['track_id']: b for b in boxes if b.get('track_id') is not None}})
        while self.frames and media_time - self.frames[0]['media_time_ms'] > 8000:
            self.frames.popleft()
        polygon = self._settings_polygon()
        if polygon != self._polygon:
            self.zone, self._polygon = ZoneTracker(), polygon
        self._refresh_zones()
        tracked = [b for b in boxes if b.get('track_id') is not None]
        box = None if tracked else self._choose_track(boxes, media_time)
        overlays = []
        if tracked:
            overlays, observations = self._update_tracks(tracked, media_time, epoch, seq)
        elif not boxes and self.tracks_seen:
            self._update_tracks([], media_time, epoch, seq)
        if box:
            overlays.append({**box, 'id': 'demo-subject', 'label': 'Person · prototype tracking', 'epoch': epoch, 'frame_seq': seq, 'media_time_ms': media_time})
            if polygon:
                event = self.zone.update(point_in_polygon((box['x'] + box['width'] / 2, box['y'] + box['height']), polygon))
                if event:
                    observations.append({'kind': 'boundary', 'observations': ['Tracked person entered configured restricted area.' if event == 'entered' else 'Person present in configured restricted area; crossing was not observed.'], 'origin': 'local_rule', 'priority': 'high', 'track_id': 'demo-subject', 'frame_seq': seq, 'media_time_ms': media_time})
        if self._task and self._task.done():
            try:
                observations.extend(self._task.result())
            except asyncio.CancelledError:
                pass
            except Exception:
                self.review_status = 'unavailable'
            self._task = None
        if self.settings.get('cloud_review_enabled') is not True:
            self.review_status, self._pending = 'disabled', None
        elif not (os.getenv('ANTHROPIC_API_KEY') and os.getenv('VISION_MODEL')):
            self.review_status, self._pending = 'not_configured', None
        else:
            # Only a local alert triggers a review (latest wins); nothing is sent while nothing happens.
            for observation in observations:
                if observation.get('origin') == 'local_rule' and observation.get('kind') in REVIEW_KINDS:
                    self._pending = (observation, list(self.frames))
            if self._task is None and self.review_status in ('disabled', 'not_configured'):
                self.review_status = 'idle'
            if self._task is None and self._pending:
                pending, self._pending = self._pending, None
                self._task = asyncio.create_task(self.review_event(*pending))
        return self._result(overlays, observations)

    def analysis_fps(self) -> float:
        """Frames actually analyzed per second over the last ~3 s (wall clock), 0 when idle."""
        now = time.monotonic()
        recent = [t for t in self.processed_at if now - t <= 3.0]
        if len(recent) < 2 or recent[-1] == recent[0]:
            return 0.0
        return round((len(recent) - 1) / (recent[-1] - recent[0]), 1)

    def _result(self, overlays, observations, **extra):
        return {'overlays': overlays, 'observations': observations, 'health': {'tracking': self.tracking_status, 'review': self.review_status, 'detector': self.detector}, 'tracking_status': self.tracking_status, 'review_status': self.review_status, 'review': self.last_review, 'cloud': self.cloud, 'detectors': {**self.events.status(), 'predictive': self._predictive_status()}, 'limitations': ['Prototype adult person tracking; not validated for infants or toddlers.', 'Airway status cannot be determined from video.'], **extra}

    async def review_event(self, observation: dict, frames: list[dict]) -> list[dict]:
        """Claude second opinion on a local alert. The incident already exists; this only adds context."""
        generation = self._generation
        if self.cloud['requests'] >= int(os.getenv('MAX_MODEL_REQUESTS_PER_SESSION', '200')):
            self.review_status = 'budget_exhausted'
            return []
        track = str(observation.get('track_id', '')).removeprefix('person-')
        recent = [f for f in frames if 0 <= observation['media_time_ms'] - f['media_time_ms'] <= 3000]
        crops = await asyncio.to_thread(crop_frames, recent, int(track)) if track.isdigit() else []
        if not crops or generation != self._generation:
            return []
        self.review_status = 'reviewing'
        self.cloud['requests'] += 1
        try:
            if self._client is None:
                from anthropic import AsyncAnthropic
                self._client = AsyncAnthropic(timeout=20.0, max_retries=1)
            outcome = await second_opinion(self._client, os.environ['VISION_MODEL'], KINDS[observation['kind']][0], observation['observations'][0], crops)
        except Exception:  # Provider error, decline, or invalid output: context is optional, the alert already went out.
            if generation == self._generation:
                self.review_status = 'unavailable'
            return []
        if generation != self._generation:
            return []
        self.cloud['input_tokens'] += outcome['input_tokens']
        self.cloud['output_tokens'] += outcome['output_tokens']
        if outcome['cost_usd'] is None:
            self.cloud['cost_known'] = False
        else:
            self.cloud['cost_usd'] = round(self.cloud['cost_usd'] + outcome['cost_usd'], 6)
        result = outcome['result']
        self.review_status = result.assessment
        self.last_review = {**result.model_dump(), 'model': outcome['model'], 'input_tokens': outcome['input_tokens'], 'output_tokens': outcome['output_tokens'], 'cost_usd': outcome['cost_usd'], 'frames': [seq for seq, _ in crops], 'faces_blurred': True}
        if self.on_review is not None:
            self.on_review(observation['kind'], self.last_review)
            return []
        return [{'kind': 'review', 'target_kind': observation['kind'], 'track_id': observation.get('track_id'), 'review': self.last_review, 'origin': 'model', 'frame_seq': observation['frame_seq'], 'media_time_ms': observation['media_time_ms']}]
