"""Keypoint event rules for staged demos: "check now" signals, never diagnoses.

Distances use aspect-corrected image units (x scaled by width/height) and are
normalized by each person's upright body length, so thresholds do not depend
on distance from the camera. Evidence is integrated over time (time-weighted
CUSUM or explicit durations) so a single noisy frame never alerts.
"""
from __future__ import annotations

import math
from collections import deque

import numpy as np

NOSE, L_SH, R_SH, L_WR, R_WR, L_HIP, R_HIP, L_ANK, R_ANK = 0, 5, 6, 9, 10, 11, 12, 15, 16
LIMBS = (L_WR, R_WR, L_ANK, R_ANK)
MIN_CONF = 0.4
HISTORY_S = 12.0
RHYTHM_MIN_HZ = 8.0  # Nyquist: resolving up to 4–5 Hz needs at least 8–10 samples per second.


class Cusum:
    """S_t = max(0, S_{t-1} + (score_t - k)·Δt); fire when S_t > h, so h is in evidence-seconds."""
    def __init__(self, k: float, h: float, refractory: float = 10.0):
        self.k, self.h, self.refractory = k, h, refractory
        self.s, self.last_t, self.fired_at = 0.0, None, -math.inf

    def update(self, score: float, t: float) -> bool:
        dt = 0.0 if self.last_t is None else min(max(t - self.last_t, 0.0), 1.0)  # A gap is not evidence.
        self.last_t = t
        self.s = max(0.0, self.s + (score - self.k) * dt)
        if self.s <= self.h:
            return False
        if t - self.fired_at < self.refractory:
            self.s = self.h
            return False
        self.s, self.fired_at = 0.0, t
        return True


def _point(kp, i, aspect):
    if i >= len(kp) or kp[i][2] < MIN_CONF:
        return None
    return np.array([kp[i][0] * aspect, kp[i][1]])


def _mid(a, b):
    if a is None or b is None:
        return a if b is None else b
    return (a + b) / 2


class _Track:
    def __init__(self):
        self.samples = deque()  # (t, {keypoint: point or None}, hip_mid, lying, body_height)
        self.upright_heights = deque(maxlen=20)
        self.throat = Cusum(k=0.45, h=0.8, refractory=15)
        self.rhythm = Cusum(k=0.3, h=3.0, refractory=30)
        self.drop_at = -math.inf
        self.lying_since = None
        self.collapse_at = -math.inf
        self.low_since = None
        self.low_seen = -math.inf
        self.posture = {}
        self.fall_at = -math.inf
        self.still_since = None
        self.still_at = -math.inf

    def body_length(self, current):
        return float(np.median(self.upright_heights)) if self.upright_heights else current


class EventDetector:
    def __init__(self, settings: dict | None = None):
        settings = settings or {}
        self.stillness_seconds = float(settings.get('stillness_seconds', 30))
        self.nap_mode = settings.get('nap_mode') is True
        self.tracks: dict = {}
        self.sample_rate = 0.0

    def forget(self, tid):
        self.tracks.pop(tid, None)

    def status(self) -> dict:
        return {'sample_rate_hz': round(self.sample_rate, 1),
                'rhythmic': 'active' if self.sample_rate >= RHYTHM_MIN_HZ else f'needs ≥{RHYTHM_MIN_HZ:g} fps',
                'stillness': 'suppressed (nap mode)' if self.nap_mode else 'active'}

    def update(self, tid, person: dict, t_ms: float, aspect: float = 16 / 9) -> list[dict]:
        track = self.tracks.setdefault(tid, _Track())
        t = t_ms / 1000
        kp = person.get('keypoints') or []
        points = {i: _point(kp, i, aspect) for i in (NOSE, L_SH, R_SH, L_WR, R_WR, L_HIP, R_HIP, L_ANK, R_ANK)}
        shoulders, hips = _mid(points[L_SH], points[R_SH]), _mid(points[L_HIP], points[R_HIP])
        height = person['height']
        lying = person['width'] * aspect > 1.2 * height
        angle = None
        if shoulders is not None and hips is not None:
            v = shoulders - hips
            angle = math.degrees(math.atan2(abs(v[0]), -v[1]))  # 0° upright, 90° horizontal.
            lying = lying or angle > 55
            # Learn upright height only near full height: a crouch facing the camera also looks upright.
            if angle < 30 and (not track.upright_heights or height >= 0.85 * float(np.median(track.upright_heights))):
                track.upright_heights.append(height)
        track.posture = {'height': height, 'bottom': person['y'] + person['height'], 'wide': person['width'] * aspect > 1.2 * height}
        track.samples.append((t, points, hips, lying, height))
        while track.samples and t - track.samples[0][0] > HISTORY_S:
            track.samples.popleft()
        if len(track.samples) >= 3:
            gaps = np.diff([s[0] for s in list(track.samples)[-20:]])
            gaps = gaps[gaps > 0]
            self.sample_rate = 1 / float(np.median(gaps)) if len(gaps) else 0.0
        length = track.body_length(height)
        events = []
        for check in (self._throat, self._fall, self._rhythm, self._stillness):
            event = check(track, points, shoulders, hips, lying, length, t)
            if event:
                events.append(event)
        return events

    def _throat(self, track, points, shoulders, hips, lying, length, t):
        """Universal choking sign: both wrists at the throat, sustained (~1.5 s)."""
        nose, ls, rs = points[NOSE], points[L_SH], points[R_SH]
        score = 0.0
        if nose is not None and ls is not None and rs is not None:
            throat = shoulders + 0.35 * (nose - shoulders)
            scale = float(np.linalg.norm(shoulders - hips)) if hips is not None else 1.5 * float(np.linalg.norm(ls - rs))
            near = [w is not None and np.linalg.norm(w - throat) < 0.25 * scale for w in (points[L_WR], points[R_WR])]
            score = 1.0 if all(near) else 0.4 if any(near) else 0.0
        if track.throat.update(score, t):
            return {'kind': 'distress', 'priority': 'critical', 'text': 'Both hands held at the throat for over a second (local pose rule). Ordinary eating or neck touching can look similar.'}

    def _fall(self, track, points, shoulders, hips, lying, length, t):
        """Two paths, each a fast drop followed by staying down (DET-6):
        A. hips drop > 0.3 body lengths within 1 s, then lying for 1 s;
        B. body height collapses (≥ 0.85 → ≤ 0.7 of upright within 1.5 s), then stays low for 1.5 s, box not
           lying-wide, having started with a hand at the floor. Falling toward the camera barely moves the hips in
           the image, but the height collapses; a slow lie-down ends wide and flat, so it never matches B."""
        posture = track.posture
        if hips is not None:
            recent = [s[2][1] for s in track.samples if s[2] is not None and t - s[0] <= 1.0]
            if recent and hips[1] - min(recent) > 0.3 * length:
                track.drop_at = t
        track.lying_since = (track.lying_since or t) if lying else None
        heights = [s[4] for s in track.samples if t - s[0] <= 1.5]
        if heights and max(heights) >= 0.85 * length and posture['height'] <= 0.7 * length:
            track.collapse_at = t
        hand_at_floor = any(points[w] is not None and points[w][1] >= posture['bottom'] - 0.15 * length for w in (L_WR, R_WR))
        low = posture['height'] <= 0.75 * length and not posture['wide']
        # A hand at the floor must start the low posture (not a quick sit); after that, hands may lift.
        if low and (hand_at_floor or track.low_since is not None):
            track.low_since, track.low_seen = (track.low_since or t), t
        elif track.low_since is not None and t - track.low_seen > 0.5:  # Tolerate brief keypoint dropouts.
            track.low_since = None
        on_hands = low and track.low_since is not None
        path_a = track.lying_since is not None and t - track.lying_since >= 1.0 and t - track.drop_at <= 3.0
        path_b = on_hands and track.low_since is not None and t - track.low_since >= 1.5 and t - track.collapse_at <= 3.0
        if (path_a or path_b) and t - track.fall_at > 10.0:
            track.fall_at = t
            what = 'lying position' if path_a else 'hands-and-knees position'
            return {'kind': 'fall', 'priority': 'high', 'text': f'Rapid drop to a {what} that has not reversed (local pose rule). Injury cannot be determined from video.'}

    def _rhythm(self, track, points, shoulders, hips, lying, length, t):
        """Seizure-like: ≥2 limbs with most motion power in 1–5 Hz, sustained (~4 s of evidence)."""
        score = 0.0
        window = [s for s in track.samples if t - s[0] <= 6.0]
        if self.sample_rate >= RHYTHM_MIN_HZ and len(window) >= 32 and window[-1][0] - window[0][0] >= 4.0:
            times = np.array([s[0] for s in window])
            grid = np.arange(times[0], times[-1], 1 / self.sample_rate)
            rhythmic = 0
            for limb in LIMBS:
                present = np.array([s[1][limb] is not None for s in window])
                if present.sum() < 0.8 * len(window):
                    continue
                ts = times[present]
                xy = np.array([s[1][limb] for s in window if s[1][limb] is not None])
                power, amplitude = 0.0, 0.0
                freqs = np.fft.rfftfreq(len(grid), 1 / self.sample_rate)
                band = (freqs >= 1.0) & (freqs <= 5.0)
                spectrum = np.zeros_like(freqs)
                for axis in (0, 1):
                    signal = np.interp(grid, ts, xy[:, axis])
                    signal = signal - np.polyval(np.polyfit(grid - grid[0], signal, 1), grid - grid[0])
                    amplitude += float(np.mean(signal ** 2))
                    spectrum += np.abs(np.fft.rfft(signal * np.hanning(len(signal)))) ** 2
                usable = freqs > 0.2
                total = spectrum[usable].sum()
                if total <= 0 or math.sqrt(amplitude) <= 0.02 * length:
                    continue
                # The strongest frequency must itself be 1–5 Hz, so slow waving next to the band edge
                # does not count. Rhythm concentrates power at that peak (plus its first harmonic,
                # since jerks are not sine waves); pose jitter is broadband and spreads it.
                f0 = freqs[usable][np.argmax(spectrum[usable])]
                if not 1.0 <= f0 <= 5.0:
                    continue
                near = (np.abs(freqs - f0) <= 0.5) | (np.abs(freqs - 2 * f0) <= 0.5)
                if spectrum[near].sum() / total > 0.6:
                    rhythmic += 1
            score = 1.0 if rhythmic >= 2 else 0.0
        if track.rhythm.update(score, t):
            return {'kind': 'rhythmic', 'priority': 'critical', 'text': 'Repetitive 1–5 Hz movement in two or more limbs for several seconds (local pose rule). Not a seizure diagnosis; play or dancing can look similar.'}

    def _stillness(self, track, points, shoulders, hips, lying, length, t):
        """Mean keypoint displacement over 2 s below 4% of body length, for the configured duration."""
        if self.nap_mode:
            track.still_since = None
            return None
        then = next((s for s in track.samples if t - s[0] <= 2.0), None)
        if then is None or t - then[0] < 1.5:
            return None
        moves = [np.linalg.norm(points[i] - then[1][i]) for i in points if points[i] is not None and then[1][i] is not None]
        if len(moves) < 4:
            track.still_since = None
            return None
        if float(np.mean(moves)) < 0.04 * length:
            track.still_since = track.still_since if track.still_since is not None else then[0]
        else:
            track.still_since = None
        if track.still_since is not None and t - track.still_since >= self.stillness_seconds and t - track.still_at > self.stillness_seconds:
            track.still_at = t
            return {'kind': 'stillness', 'priority': 'high', 'text': f'Very little movement for {self.stillness_seconds:g} s outside nap mode (local pose rule). Breathing cannot be determined from video.'}
