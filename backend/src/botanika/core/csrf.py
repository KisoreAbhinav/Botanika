"""Double-submit CSRF protection for browser state-changing requests."""

from __future__ import annotations

import secrets
from hmac import compare_digest

from fastapi import HTTPException, Request, Response

from botanika.core.settings import Settings


CSRF_COOKIE = "botanika_csrf"
CSRF_HEADER = "X-CSRF-Token"


def issue_token(response: Response, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=3600,
        httponly=False,
        secure=settings.access_required,
        samesite="lax",
        path="/",
    )
    return token


def validate_request(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin:
        # Compare the browser-supplied host, while allowing HTTPS termination at
        # Cloudflare/Nginx to differ from the loopback HTTP hop.
        from urllib.parse import urlsplit

        origin_host = urlsplit(origin).netloc.lower()
        request_host = request.headers.get("host", "").lower()
        if origin_host != request_host:
            raise HTTPException(status_code=403, detail={"error": "cross_origin_request"})

    if not settings.csrf_required:
        return
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get(CSRF_HEADER)
    if not cookie_token or not header_token or not compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail={"error": "csrf_token_required"})
