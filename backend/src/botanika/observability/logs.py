"""Bounded, redacted request logging for local diagnostics."""

from __future__ import annotations

from collections import deque
import threading
from typing import Any


class RequestLog:
    """Keep only the most recent request records in memory (bounded)."""

    def __init__(self, limit: int = 200) -> None:
        if limit <= 0:
            raise ValueError("request log limit must be positive")
        self.limit = limit
        self._lock = threading.Lock()
        self._entries: deque[dict[str, Any]] = deque(maxlen=limit)

    def record(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        logged_at: float,
    ) -> None:
        with self._lock:
            self._entries.append(
                {
                    "logged_at": logged_at,
                    "request_id": request_id,
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": round(duration_ms, 3),
                }
            )

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._entries)