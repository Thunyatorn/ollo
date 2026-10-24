"""CUSUM: alert on sustained evidence, not on a single spike. See MATH.md section 7."""


class Cusum:
    """A leaky bucket. Each step adds (evidence - k) * dt; alert when it holds h evidence-seconds.

    Because the bucket is emptied at every alert and held at zero during cooldown, it never exceeds h by more than
    one step, so no upper clamp is needed (MATH 7.4).
    """

    def __init__(self, k: float = 0.3, h: float = 0.2, cooldown: float = 60.0):
        self.k, self.h, self.cooldown = k, h, cooldown
        self.S = 0.0
        self.cool_until = float("-inf")

    def update(self, e: float, dt: float, t: float, armed: bool = True) -> bool:
        """Returns True on the step where the alert fires. `armed=False` (zone off by schedule) empties the bucket."""
        if not armed or t < self.cool_until:
            self.S = 0.0
            return False
        self.S = max(0.0, self.S + (e - self.k) * dt)
        if self.S >= self.h - 1e-12:
            self.S = 0.0
            self.cool_until = t + self.cooldown
            return True
        return False


class CusumBank:
    """One bucket per (track, zone) pair, with the frame time step worked out from timestamps."""

    def __init__(self, k: float = 0.3, h: float = 0.2, cooldown: float = 60.0, first_dt: float = 0.125, max_dt: float = 0.15):
        self._args = (k, h, cooldown)
        self.first_dt, self.max_dt = first_dt, max_dt
        self._cusums: dict = {}
        self._last_t: dict = {}

    def update(self, key, e: float, t: float, armed: bool = True) -> bool:
        if key not in self._cusums:
            self._cusums[key] = Cusum(*self._args)
        last = self._last_t.get(key)
        dt = self.first_dt if last is None else min(max(t - last, 0.0), self.max_dt)   # a stalled frame counts for at most 0.15 s, so a hiccup plus one bad frame cannot alert by itself
        self._last_t[key] = t
        return self._cusums[key].update(e, dt, t, armed)

    def forget_track(self, track_id) -> None:
        for key in [k for k in self._cusums if k[0] == track_id]:
            del self._cusums[key], self._last_t[key]

    def level(self, key) -> float:
        c = self._cusums.get(key)
        return c.S if c else 0.0
