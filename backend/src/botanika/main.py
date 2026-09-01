"""FastAPI entrypoint for Botanika's first phone-to-Pi connectivity stage."""

from __future__ import annotations

import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from botanika import __version__
from botanika.api.receipt import DuplicateRequestError, ReceiptStore, ReceiptValidationError
from botanika.api.status import StatusHub, utc_now
from botanika.core.access import AccessAuthenticationError, AccessConfigurationError, AccessVerifier
from botanika.core.csrf import issue_token, validate_request
from botanika.core.middleware import RequestBodyLimitMiddleware, SecurityHeadersMiddleware
from botanika.core.rate_limit import SlidingWindowRateLimiter
from botanika.core.settings import Settings


LOGGER = logging.getLogger("botanika.connectivity")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or Settings.from_env()
    receipt_store = ReceiptStore(app_settings)
    receipt_rate_limiter = SlidingWindowRateLimiter(
        app_settings.receipt_rate_limit, app_settings.receipt_rate_window_seconds
    )
    status_hub = StatusHub(app_settings)
    access_verifier = AccessVerifier(app_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        app_settings.temporary_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title=app_settings.app_name, version=app_settings.app_version, lifespan=lifespan)
    app.state.settings = app_settings
    app.state.receipt_store = receipt_store
    app.state.status_hub = status_hub

    # Middleware is ordered from outermost to innermost by Starlette. The body
    # limit therefore applies before multipart parsing and the headers apply to
    # every ordinary HTTP response.
    app.add_middleware(RequestBodyLimitMiddleware, max_bytes=app_settings.max_request_bytes)
    app.add_middleware(SecurityHeadersMiddleware)

    async def require_access(request: Request) -> dict[str, Any]:
        try:
            return access_verifier.verify(request.headers.get("CF-Access-JWT-Assertion"))
        except AccessAuthenticationError as exc:
            raise HTTPException(status_code=401, detail={"error": "access_required", "message": str(exc)}) from exc
        except AccessConfigurationError as exc:
            LOGGER.error("Cloudflare Access verification is not configured")
            raise HTTPException(status_code=503, detail={"error": "access_not_configured"}) from exc

    def request_id_from(request: Request) -> str:
        idempotency_id = request.headers.get("Idempotency-Key")
        request_id = request.headers.get("X-Request-ID")
        if idempotency_id and request_id and idempotency_id != request_id:
            raise HTTPException(status_code=400, detail={"error": "request_id_conflict"})
        candidate = idempotency_id or request_id or str(uuid4())
        if not _REQUEST_ID_RE.fullmatch(candidate):
            raise HTTPException(status_code=400, detail={"error": "invalid_request_id"})
        return candidate

    async def require_csrf(request: Request) -> None:
        validate_request(request, app_settings)

    @app.get("/api/v1/health/live")
    async def health_live() -> dict[str, Any]:
        return {"status": "ok", "service": app_settings.app_name, "version": __version__}

    @app.get("/api/v1/health/ready")
    async def health_ready() -> JSONResponse:
        temp_ready = app_settings.temporary_dir.is_dir()
        frontend_ready = (app_settings.frontend_dir / "index.html").is_file()
        temporary_file_count = sum(
            1
            for path in app_settings.temporary_dir.iterdir()
            if path.is_file() and path.name != ".gitkeep"
        ) if temp_ready else 0
        checks = {
            "process": "ready",
            "temporary_storage": "ready" if temp_ready else "unavailable",
            "placeholder_ui": "ready" if frontend_ready else "unavailable",
            "access_verification": "configured" if not app_settings.access_required or (
                app_settings.access_audience and app_settings.access_jwks_url and app_settings.access_team_domain
            ) else "unavailable",
        }
        ready = all(value not in {"unavailable"} for value in checks.values())
        payload = {
            "status": "ready" if ready else "not_ready",
            "checks": checks,
            "temporary_file_count": temporary_file_count,
            "idempotency_cache_entries": receipt_store.cached_count(),
        }
        return JSONResponse(payload, status_code=200 if ready else 503)

    @app.get("/api/v1/status")
    async def status(_: dict[str, Any] = Depends(require_access)) -> dict[str, Any]:
        return {
            "service": app_settings.app_name,
            "version": app_settings.app_version,
            "environment": app_settings.environment,
            "mode": "CONNECTIVITY_PLACEHOLDER",
            "image_transport": "binary_multipart_only",
            "live_video_transport": False,
            "temporary_file_count": sum(
                1
                for path in app_settings.temporary_dir.iterdir()
                if path.is_file() and path.name != ".gitkeep"
            ) if app_settings.temporary_dir.is_dir() else 0,
            "idempotency_cache_entries": receipt_store.cached_count(),
            "server_time": utc_now(),
        }

    @app.get("/api/v1/security/csrf")
    async def csrf_token(response: Response) -> dict[str, str]:
        token = issue_token(response, app_settings)
        return {"token": token}

    @app.post("/api/v1/connectivity/receipt")
    async def receive_receipt(
        request: Request,
        access_claims: dict[str, Any] = Depends(require_access),
        __: None = Depends(require_csrf),
        image: UploadFile = File(description="One cropped JPEG or WebP image"),
        metadata: str | None = Form(None),
    ) -> JSONResponse:
        request_id = "request-id-unavailable"
        try:
            request_id = request_id_from(request)
            identity = access_claims.get("email")
            if not identity:
                identity = request.client.host if request.client else "unknown"
            rate_key = str(identity)
            if not receipt_rate_limiter.allow(rate_key):
                raise HTTPException(
                    status_code=429,
                    headers={"Retry-After": str(app_settings.receipt_rate_window_seconds)},
                    detail={
                        "request_id": request_id,
                        "accepted": False,
                        "error": "rate_limited",
                        "message": "too many crop receipts; try again later",
                    },
                )

            if metadata:
                if len(metadata.encode("utf-8")) > 32 * 1024:
                    raise HTTPException(
                        status_code=413,
                        detail={"request_id": request_id, "accepted": False, "error": "metadata_too_large"},
                    )
                try:
                    decoded_metadata = json.loads(metadata)
                except json.JSONDecodeError as exc:
                    raise HTTPException(
                        status_code=400,
                        detail={"request_id": request_id, "accepted": False, "error": "invalid_metadata"},
                    ) from exc
                if not isinstance(decoded_metadata, dict):
                    raise HTTPException(
                        status_code=400,
                        detail={"request_id": request_id, "accepted": False, "error": "invalid_metadata"},
                    )

            data = await image.read(app_settings.max_image_bytes + 1)
            if len(data) > app_settings.max_image_bytes:
                raise ReceiptValidationError("image_too_large", "image exceeds the byte limit")
            receipt = await receipt_store.receive(request_id, data, image.content_type or "")
        except ReceiptValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "request_id": request_id,
                    "accepted": False,
                    "error": exc.code,
                    "message": exc.message,
                },
            ) from exc
        except DuplicateRequestError as exc:
            raise HTTPException(
                status_code=409,
                detail={"request_id": request_id, "accepted": False, "error": "idempotency_conflict", "message": str(exc)},
            ) from exc
        finally:
            # UploadFile may have used a spooled temporary file. Closing it is
            # what releases that file on every success and error path.
            await image.close()

        LOGGER.info(
            "crop receipt accepted request_id=%s bytes=%d dimensions=%dx%d mime=%s",
            receipt.request_id,
            receipt.byte_count,
            receipt.width,
            receipt.height,
            receipt.mime_type,
        )
        await status_hub.broadcast(
            {
                "type": "receipt-received",
                "request_id": receipt.request_id,
                "byte_count": receipt.byte_count,
                "server_time": receipt.received_at,
            }
        )
        return JSONResponse(receipt.as_dict())

    async def serve_websocket(websocket: WebSocket) -> None:
        try:
            access_verifier.verify(websocket.headers.get("CF-Access-JWT-Assertion"))
        except (AccessAuthenticationError, AccessConfigurationError):
            await websocket.close(code=1008, reason="Cloudflare Access authentication required")
            return
        await status_hub.serve(websocket)

    @app.websocket("/ws/status")
    async def websocket_status(websocket: WebSocket) -> None:
        await serve_websocket(websocket)

    @app.websocket("/ws/session")
    async def websocket_session(websocket: WebSocket) -> None:
        await serve_websocket(websocket)

    frontend_dir = app_settings.frontend_dir
    source_dir = frontend_dir / "src"
    if source_dir.is_dir():
        app.mount("/src", StaticFiles(directory=source_dir), name="frontend-source")

    @app.get("/manifest.webmanifest")
    async def manifest() -> Response:
        path = frontend_dir / "manifest.webmanifest"
        if path.is_file():
            return Response(path.read_text(encoding="utf-8"), media_type="application/manifest+json")
        return JSONResponse({"name": app_settings.app_name, "start_url": "/"})

    @app.get("/sw.js")
    async def service_worker() -> Response:
        path = frontend_dir / "sw.js"
        if path.is_file():
            return Response(path.read_text(encoding="utf-8"), media_type="application/javascript")
        return Response("", media_type="application/javascript")

    @app.get("/")
    async def index() -> Response:
        path = frontend_dir / "index.html"
        if path.is_file():
            return HTMLResponse(path.read_text(encoding="utf-8"))
        return JSONResponse({"service": app_settings.app_name, "status": "placeholder"})

    return app


app = create_app()
