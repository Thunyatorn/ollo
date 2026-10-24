"""The local alarm: a loud sound from this computer's speaker. See CLUADE.md, "Wrist buzzer and local alarm".

It plays while ANY reason is active (an unanswered alert, or a high alert while the internet is down), and stops when the
last reason is cleared. It does not depend on the network, the cloud or the worker.
"""
import logging
import platform
import shutil
import subprocess
import sys
import threading
import time
from typing import Callable

log = logging.getLogger("nestwatch.alarm")


def default_play_once() -> None:
    """One cycle of the alarm sound. macOS and Linux use a system sound; anything else falls back to the terminal bell."""
    system = platform.system()
    cmd = None
    if system == "Darwin" and shutil.which("afplay"):
        cmd = ["afplay", "-v", "2", "/System/Library/Sounds/Sosumi.aiff"]
    elif system == "Linux" and shutil.which("paplay"):
        cmd = ["paplay", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"]
    if cmd:
        subprocess.run(cmd, timeout=10, check=False)
    else:
        sys.stderr.write("\a")
        sys.stderr.flush()
        time.sleep(0.8)


class AlarmPlayer:
    def __init__(self, play_once: Callable[[], None] | None = None, gap_s: float = 0.2):
        self._play = play_once or default_play_once
        self._gap = gap_s
        self._reasons: dict[str, float | None] = {}     # reason -> auto-stop time (monotonic), or None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop_all = False
        self.cycles = 0
        self._thread = threading.Thread(target=self._run, daemon=True, name="alarm")
        self._thread.start()

    def start(self, reason: str, duration_s: float | None = None) -> None:
        with self._lock:
            if reason not in self._reasons:
                log.warning("LOCAL ALARM ON: %s", reason)
            self._reasons[reason] = None if duration_s is None else time.monotonic() + duration_s
        self._wake.set()

    def stop(self, reason: str) -> None:
        with self._lock:
            if self._reasons.pop(reason, "absent") != "absent":
                log.warning("local alarm reason cleared: %s", reason)

    @property
    def active(self) -> bool:
        now = time.monotonic()
        with self._lock:
            return any(until is None or until > now for until in self._reasons.values())

    def reasons(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            return [r for r, until in self._reasons.items() if until is None or until > now]

    def _run(self) -> None:
        while not self._stop_all:
            if self.active:
                try:
                    self._play()
                    self.cycles += 1
                except Exception:
                    log.exception("alarm sound failed")
                    time.sleep(1.0)
                time.sleep(self._gap)
            else:
                self._wake.wait(0.5)
                self._wake.clear()

    def close(self) -> None:
        self._stop_all = True
        self._wake.set()
        self._thread.join(timeout=3.0)
