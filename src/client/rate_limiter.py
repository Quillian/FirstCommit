from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_sec: int = 60) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._lock = threading.Lock()
        self._timestamps: deque[float] = deque()

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.time()
                while self._timestamps and (now - self._timestamps[0]) > self.window_sec:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return
                sleep_for = self.window_sec - (now - self._timestamps[0])
            time.sleep(max(sleep_for, 0.01))
