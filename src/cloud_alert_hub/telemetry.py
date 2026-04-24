from __future__ import annotations

from collections import defaultdict
from threading import Lock


class MetricsTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = defaultdict(int)

    def inc(self, metric: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[metric] += amount

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)
