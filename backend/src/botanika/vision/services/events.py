"""Bounded thread-safe event hub for the Scan SSE channel."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
import threading

from .snapshot import ScanSnapshot


class EventHub:
    """Keep the latest bounded snapshots and let multiple SSE clients poll.

    Old events beyond the configured backlog boundary are dropped for new
    producers, while a slow consumer always receives a fresh snapshot every
    poll cycle from ``latest()``.
    """

    def __init__(self, backlog: int = 50) -> None:
        if backlog <= 0:
            raise ValueError("event backlog must be positive")
        self.backlog = backlog
        self._lock = threading.Lock()
        self._items: deque[ScanSnapshot] = deque(maxlen=backlog)
        self._sequence = 0

    @property
    def last_sequence(self) -> int:
        with self._lock:
            return self._sequence

    def publish(self, snapshot: ScanSnapshot) -> ScanSnapshot:
        with self._lock:
            self._sequence += 1
            published = replace(snapshot, sequence=self._sequence)
            self._items.append(published)
            return published

    def latest(self) -> ScanSnapshot | None:
        with self._lock:
            return self._items[-1] if self._items else None

    def after(self, last_sequence: int) -> list[ScanSnapshot]:
        """Return snapshots whose sequence is greater than ``last_sequence``."""

        with self._lock:
            return [item for item in self._items if item.sequence > last_sequence]