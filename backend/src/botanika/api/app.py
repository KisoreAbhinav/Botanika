"""FastAPI modular-monolith application factory for Botanika Phase 6."""

from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import mimetypes
from pathlib import Path
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response

from botanika.api.routes import capabilities_router, health_router, library_router, scan_router, species_router
from botanika.api.runtime import APP_VERSION, Runtime, get_runtime
from botanika.core.errors import BotanikaError, NotFoundError, ProblemDetail
from botanika.core.settings import AppSettings, FRONTEND_DIST
from botanika.observability import RequestLog
from botanika.knowledge import KnowledgeStore
from botanika.storage import DemoLibrary, DiscoveryLibrary
from botanika.vision.services import ScanService

LOGGER = logging.getLogger("botanika.phase6.api")


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Build the local application with lifecycle, routes, and error handling."""

    settings = settings or AppSettings()
    app = FastAPI(
        title="Botanika",
        version=APP_VERSION,
        lifespan=_lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        default_response_class=JSONResponse,
    )
    app.state.settings = settings

    _install_middleware(app)
    _install_error_handlers(app)

    app.include_router(health_router, prefix="/api/v1")
    app.include_router(capabilities_router, prefix="/api/v1")
    app.include_router(scan_router, prefix="/api/v1")
    app.include_router(library_router, prefix="/api/v1")
    app.include_router(species_router, prefix="/api/v1")

    @app.get("/api/v1/diagnostics/logs", include_in_schema=False)
    async def diagnostics_logs(request: Request) -> list[dict[str, Any]]:
        return get_runtime(request).request_log.list()

    _mount_static(app, settings)
    return app
@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = app.state.settings
    request_log = RequestLog(settings.request_log_limit)
    knowledge = KnowledgeStore(
        settings.database_path,
        settings.species_catalog_path,
    )
    if settings.legacy_demo_mode:
        library = DemoLibrary(
            settings.database_path,
            settings.demo_discoveries_dir,
            deduplication_seconds=settings.demo_save_deduplication_seconds,
        )
    else:
        library = DiscoveryLibrary(
            settings.database_path,
            settings.discoveries_dir,
            deduplication_seconds=settings.save_deduplication_seconds,
            quota_bytes=settings.library_quota_bytes,
            quota_observations=settings.library_quota_observations,
        )
    scan = ScanService(settings, use_production_classifier=not settings.legacy_demo_mode)
    app.state.runtime = Runtime(
        settings=settings,
        scan=scan,
        library=library,
        knowledge=knowledge,
        request_log=request_log,
    )
    LOGGER.info(
        "Botanika %s starting on %s:%s (loopback only)",
        APP_VERSION,
        settings.host,
        settings.port,
    )
    scan.start()
    try:
        yield
    finally:
        scan.stop(timeout=3.0)
        library.close()
        knowledge.close()


def _install_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            LOGGER.exception("Unhandled request failure for %s %s", request.method, request.url.path)
            response = JSONResponse(
                ProblemDetail(
                    type="about:blank",
                    title="Internal server error",
                    status=500,
                    detail="The local service failed while handling the request.",
                    code="internal_error",
                    request_id=request_id,
                ).to_dict(),
                status_code=500,
            )
        response.headers["X-Request-Id"] = request_id
        duration_ms = (time.perf_counter() - started) * 1000.0
        runtime: Runtime | None = getattr(request.app.state, "runtime", None)
        if runtime is not None:
            runtime.request_log.record(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                logged_at=time.time(),
            )
        return response


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(BotanikaError)
    async def botanika_error(request: Request, exc: BotanikaError):
        return JSONResponse(
            ProblemDetail(
                type="about:blank",
                title=exc.message,
                status=exc.http_status,
                detail=exc.detail or exc.message,
                code=exc.code,
                request_id=getattr(request.state, "request_id", None),
            ).to_dict(),
            status_code=exc.http_status,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        messages = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'body'}: {error['msg']}"
            for error in exc.errors()
        )
        return JSONResponse(
            ProblemDetail(
                type="about:blank",
                title="Request validation failed",
                status=422,
                detail=messages,
                code="invalid_request",
                request_id=getattr(request.state, "request_id", None),
            ).to_dict(),
            status_code=422,
        )


def _mount_static(app: FastAPI, settings: AppSettings) -> None:
    media_dir = settings.discoveries_dir
    media_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/media/discoveries/{media_path:path}", include_in_schema=False)
    async def discovery_media(media_path: str):
        return _local_file_response(media_dir, media_path)

    # Keep the old path available for an already-created Phase 5 demo folder;
    # the Phase 6 runtime never writes to it or reports it as a discovery.
    demo_dir = settings.demo_discoveries_dir
    demo_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/media/demo/{media_path:path}", include_in_schema=False)
    async def demo_media(media_path: str):
        return _local_file_response(demo_dir, media_path)

    if FRONTEND_DIST.is_dir():
        index_html = (FRONTEND_DIST / "index.html").read_text(encoding="utf-8")

        @app.get("/", include_in_schema=False)
        async def frontend_index():
            return HTMLResponse(index_html)

        @app.get("/{asset_path:path}", include_in_schema=False)
        async def frontend_asset(asset_path: str):
            if asset_path.startswith(("api/", "media/")):
                raise NotFoundError("local resource not found")
            if not Path(asset_path).suffix:
                return HTMLResponse(index_html)
            return _local_file_response(FRONTEND_DIST, asset_path)

        return

    @app.get("/", include_in_schema=False)
    async def frontend_pending():
        return HTMLResponse(
            "<html><body style='font-family: Georgia, serif;background:#efede3;color:#272724'>"
            "<h1>Botanika</h1><p>The frontend has not been built yet. "
            "Run <code>npm run build</code> inside <code>frontend/</code>, then restart.</p>"
            "</body></html>",
            status_code=503,
        )


def _local_file_response(root: Path, relative_path: str) -> Response:
    """Serve one small loopback asset without an implicit worker-thread pool."""

    candidate = (root / relative_path).resolve()
    resolved_root = root.resolve()
    if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
        raise NotFoundError("local resource not found")
    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return Response(candidate.read_bytes(), media_type=media_type)
