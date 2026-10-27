import math
import threading
import time
from typing import Callable, Dict, List, Optional


class RateLimiter:
    """Per-key request limit over a rolling minute.

    Uses the sliding-window-counter method: two counters per key (this window
    and the previous one), so memory stays constant per key however busy it
    is. State lives in memory, so each server process limits on its own.
    """

    def __init__(
        self,
        window_seconds: float = 60.0,
        max_keys: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        # key -> [window index, count in that window, count in the window before]
        self._state: Dict[str, List[int]] = {}

    def hit(self, key: str, limit: int) -> Optional[int]:
        """Counts one request. Returns None if allowed, else seconds to wait."""
        if limit <= 0:
            return None
        now = self._clock()
        window = int(now // self._window)
        with self._lock:
            state = self._state.get(key)
            if state is None:
                if len(self._state) >= self._max_keys:
                    self._evict(window)
                state = self._state[key] = [window, 0, 0]
            elif state[0] != window:
                previous = state[1] if state[0] == window - 1 else 0
                state[0], state[1], state[2] = window, 0, previous

            elapsed = (now % self._window) / self._window
            estimate = state[2] * (1.0 - elapsed) + state[1]
            if estimate >= limit:
                return max(1, math.ceil(self._window - (now % self._window)))
            state[1] += 1
            return None

    def reset(self):
        with self._lock:
            self._state.clear()

    def _evict(self, window: int):
        # Keys not seen in the current or previous window have no effect on
        # any decision, so they can go first.
        idle = [key for key, state in self._state.items() if state[0] < window - 1]
        for key in idle:
            del self._state[key]
        if len(self._state) >= self._max_keys:
            oldest = sorted(self._state, key=lambda k: self._state[k][0])
            for key in oldest[: len(self._state) - self._max_keys + 1]:
                del self._state[key]
