"""WebSocket status/heartbeat support; image transport remains REST-only."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from botanika.core.settings import Settings


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class StatusHub:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, event: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients)
        stale: list[WebSocket] = []
        for websocket in clients:
            try:
                await websocket.send_json(event)
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)

    async def serve(self, websocket: WebSocket) -> None:
        await self.connect(websocket)
        try:
            await websocket.send_json(
                {
                    "type": "connected",
                    "service": "botanika",
                    "environment": self.settings.environment,
                    "heartbeat_interval_seconds": self.settings.websocket_heartbeat_seconds,
                    "server_time": utc_now(),
                }
            )
            while True:
                try:
                    message = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=self.settings.websocket_heartbeat_seconds,
                    )
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "heartbeat", "server_time": utc_now()})
                    continue

                message_type = message.get("type") if isinstance(message, dict) else None
                if message_type in {"ping", "heartbeat"}:
                    await websocket.send_json({"type": "pong", "server_time": utc_now()})
                else:
                    await websocket.send_json({"type": "status", "server_time": utc_now()})
        except WebSocketDisconnect:
            pass
        finally:
            await self.disconnect(websocket)
