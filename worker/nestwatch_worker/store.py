"""Small in-memory stores: who a bearer token belongs to, and the blurred key frames the vision service sends."""
import hashlib
import time

from .spacetime import SAFE_ID, Rejected, Spacetime

MAX_FRAMES = 3
MAX_FRAME_BYTES = 1_500_000
MAX_CLIPS = 500


class TokenChecker:
    """Asks Spacetime who a caller is: the `my_role` view, read WITH the caller's token, answers for that identity.
    A forged or unknown token gets no row. Answers are cached for a minute (keyed by a hash, not the token)."""

    def __init__(self, stdb: Spacetime, ttl_s: float = 60.0, clock=time.monotonic):
        self.stdb, self.ttl_s, self.clock = stdb, ttl_s, clock
        self._cache: dict[str, tuple[float, dict | None]] = {}

    async def who(self, token: str) -> dict | None:
        if not token or len(token) > 4096:
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        hit = self._cache.get(key)
        if hit and hit[0] > self.clock():
            return hit[1]
        try:
            found = await self.stdb.sql("SELECT role, caregiver_id FROM my_role", token=token)
        except Rejected:                                     # Spacetime refused the token itself
            found = []
        who = found[0] if found else None
        if len(self._cache) > 1000:
            self._cache.clear()
        self._cache[key] = (self.clock() + self.ttl_s, who)
        return who


class KeyframeStore:
    """Up to three blurred JPEGs per event, keyed by the event's clip_ref, kept for 24 hours (CLUADE.md link 7)."""

    def __init__(self, ttl_s: float = 24 * 3600, clock=time.time):
        self.ttl_s, self.clock = ttl_s, clock
        self._clips: dict[str, tuple[float, list[bytes]]] = {}

    @staticmethod
    def check(clip_ref: str, frames: list[bytes]) -> str | None:
        """Why this upload is refused, or None."""
        if not SAFE_ID.match(clip_ref or ""):
            return "clip_ref must be letters, digits, '_', '-' or '.'"
        if not 1 <= len(frames) <= MAX_FRAMES:
            return f"send 1 to {MAX_FRAMES} frames"
        for f in frames:
            if len(f) > MAX_FRAME_BYTES or not f.startswith(b"\xff\xd8"):
                return "each frame must be a JPEG under 1.5 MB"
        return None

    def put(self, clip_ref: str, frames: list[bytes]) -> None:
        self.prune()
        if len(self._clips) >= MAX_CLIPS:
            del self._clips[min(self._clips, key=lambda k: self._clips[k][0])]   # drop the oldest
        self._clips[clip_ref] = (self.clock(), list(frames))

    def get(self, clip_ref: str) -> list[bytes]:
        item = self._clips.get(clip_ref)
        return list(item[1]) if item and self.clock() - item[0] < self.ttl_s else []

    def prune(self) -> None:
        now = self.clock()
        for k in [k for k, (t, _) in self._clips.items() if now - t >= self.ttl_s]:
            del self._clips[k]

    def __len__(self) -> int:
        return len(self._clips)
