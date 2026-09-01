"""Small ASGI middleware used at the internet-facing origin boundary."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any


ASGIApp = Callable[[dict[str, Any], Callable[..., Awaitable[Any]], Callable[..., Awaitable[Any]]], Awaitable[Any]]


async def _send_json(send: Callable[..., Awaitable[Any]], status: int, body: dict[str, Any]) -> None:
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(encoded)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": encoded})


class RequestBodyLimitMiddleware:
    """Reject bodies above the configured limit, including chunked requests."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[Any]], send: Callable[..., Awaitable[Any]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = self.max_bytes + 1
            if declared_length > self.max_bytes:
                await _send_json(
                    send,
                    413,
                    {"detail": {"error": "request_too_large", "max_bytes": self.max_bytes}},
                )
                return

        received = 0
        response_started = False

        async def limited_send(message: dict[str, Any]) -> None:
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        async def limited_receive() -> dict[str, Any]:
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, limited_send)
        except _RequestBodyTooLarge:
            if not response_started:
                await _send_json(
                    send,
                    413,
                    {"detail": {"error": "request_too_large", "max_bytes": self.max_bytes}},
                )


class SecurityHeadersMiddleware:
    """Add headers appropriate for the placeholder and API responses."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[Any]], send: Callable[..., Awaitable[Any]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {key.lower() for key, _ in headers}
                additions = [
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"permissions-policy", b"camera=(self), geolocation=(self), microphone=()"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
                ]
                if scope.get("path", "").startswith("/api/"):
                    additions.append((b"cache-control", b"no-store"))
                for key, value in additions:
                    if key not in existing:
                        headers.append((key, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, secure_send)


class _RequestBodyTooLarge(Exception):
    """Internal control-flow exception for the request-size middleware."""
