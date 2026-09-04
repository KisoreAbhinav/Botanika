"""FastAPI modular-monolith application factory for Botanika Phase 9."""

from __future__ import annotations

from contextlib import asynccontextmanager
from html import escape
import logging
import mimetypes
from pathlib import Path
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response

from botanika.api.routes import (
    capabilities_router,
    health_router,
    library_router,
    mode_router,
    network_router,
    scan_router,
    species_router,
    voice_router,
    weeds_router,
)
from botanika.api.auth import (
    mode_status_for_request,
    require_local_operator,
    require_local_or_controller,
)
from botanika.api.runtime import APP_VERSION, Runtime, get_runtime
from botanika.core.errors import BotanikaError, NotFoundError, ProblemDetail
from botanika.core.settings import AppSettings, FRONTEND_DIST
from botanika.observability import RequestLog
from botanika.knowledge import KnowledgeStore
from botanika.network import NetworkService
from botanika.hardware.gpio import create_mode_gpio
from botanika.mode import Mode, ModeService
from botanika.storage import DemoLibrary, DiscoveryLibrary
from botanika.storage import WeedObservationStore
from botanika.knowledge.llm import LocalLLM
from botanika.vision.services import ScanService
from botanika.vision.weeds import WeedService
from botanika.voice import AudioCoordinator

LOGGER = logging.getLogger("botanika.phase9.api")


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
    app.include_router(network_router, prefix="/api/v1")
    app.include_router(mode_router, prefix="/api/v1")
    app.include_router(voice_router, prefix="/api/v1")
    app.include_router(weeds_router, prefix="/api/v1")

    @app.get("/api/v1/diagnostics/logs", include_in_schema=False)
    async def diagnostics_logs(request: Request) -> list[dict[str, Any]]:
        require_local_operator(request)
        return get_runtime(request).request_log.list()

    _mount_static(app, settings)
    return app


@asynccontextmanager
async def _lifespan(app: FastAPI):
    settings = app.state.settings
    _prepare_runtime_dirs(settings)
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
    llm = LocalLLM(
        settings.llm_model_path,
        backend=settings.llm_backend,
        context_tokens=settings.llm_context_tokens,
        threads=settings.llm_threads,
        batch_size=settings.llm_batch_size,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    voice = AudioCoordinator(settings)
    weed_observations = None
    if not settings.legacy_demo_mode:
        weed_observations = WeedObservationStore(
            database=library.database,
            max_accuracy_m=settings.weed_position_max_accuracy_m,
        )
    weeds = WeedService(settings, observation_store=weed_observations)
    network = NetworkService(settings)
    mode = ModeService(settings, network_available=lambda: network.status().available)

    def on_mode_change(current: Mode) -> None:
        """Start/stop the optional tunnel outside the API request path."""

        if current is Mode.SOLO:
            network.stop_tunnel()
        elif settings.tunnel_enabled:
            # QuickTunnelService.start() only launches a worker and returns;
            # cloudflared startup/output parsing never blocks this callback.
            if network.tunnel_status().state in {"idle", "failed"}:
                network.start_tunnel()

    mode.add_mode_listener(on_mode_change)
    gpio = create_mode_gpio(settings, mode.toggle)
    mode.add_mode_listener(gpio.set_mode)
    mode.add_mode_listener(scan.set_application_mode)
    app.state.runtime = Runtime(
        settings=settings,
        scan=scan,
        library=library,
        knowledge=knowledge,
        request_log=request_log,
        network=network,
        mode=mode,
        gpio=gpio,
        llm=llm,
        voice=voice,
        weeds=weeds,
        weed_observations=weed_observations,
    )
    LOGGER.info(
        "Botanika %s starting on %s:%s (%s)",
        APP_VERSION,
        settings.host,
        settings.port,
        (
            "loopback safety fallback; private AP requested"
            if settings.network_enabled and settings.loopback_only
            else "private AP plus loopback"
            if settings.network_enabled
            else "loopback only"
        ),
    )
    scan.start()
    try:
        yield
    finally:
        network.stop_tunnel()
        scan.stop(timeout=3.0)
        if gpio is not None:
            gpio.cleanup()
        if weed_observations is not None:
            weed_observations.close()
        library.close()
        knowledge.close()


def _prepare_runtime_dirs(settings: AppSettings) -> None:
    """Create only the bounded application-owned data directories at startup."""

    paths = (
        Path(settings.database_path).parent,
        Path(settings.temp_crops_dir),
        Path(settings.discoveries_dir),
        Path(settings.backup_dir),
    )
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


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
    async def discovery_media(request: Request, media_path: str):
        require_local_or_controller(get_runtime(request), request)
        return _local_file_response(media_dir, media_path)

    # Keep the old path available for an already-created Phase 5 demo folder;
    # the Phase 6 runtime never writes to it or reports it as a discovery.  A
    # production service account must not create directories inside the
    # read-only application checkout, so only legacy test/demo settings may
    # initialize this compatibility path.
    demo_dir = settings.demo_discoveries_dir
    if settings.legacy_demo_mode:
        demo_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/media/demo/{media_path:path}", include_in_schema=False)
    async def demo_media(request: Request, media_path: str):
        require_local_or_controller(get_runtime(request), request)
        return _local_file_response(demo_dir, media_path)

    @app.get("/connect", include_in_schema=False)
    async def network_landing(request: Request):
        """Serve a no-JavaScript landing page for a phone on the private AP."""

        runtime = get_runtime(request)
        network = runtime.network
        if network is None:  # pragma: no cover - defensive for old embedders
            return HTMLResponse(
                _render_network_landing(
                    enabled=False,
                    available=False,
                    state="unavailable",
                    detail="Network status is not initialized.",
                    config=None,
                )
            )
        network_data = network.to_dict()
        status = network.status()
        tunnel = network_data.get("tunnel")
        tunnel_enabled = isinstance(tunnel, dict) and bool(tunnel.get("enabled"))
        tunnel_ready = tunnel_enabled and tunnel.get("state") == "ready"
        mode_status = (
            mode_status_for_request(
                runtime.mode.status(network=network_data),
                request,
            )
            if runtime.mode
            else None
        )
        return HTMLResponse(
            _render_network_landing(
                enabled=status.enabled or tunnel_enabled,
                available=status.available or tunnel_ready,
                state=(str(tunnel.get("state")) if tunnel_enabled else status.state),
                detail=(str(tunnel.get("detail")) if tunnel_enabled else status.detail),
                config=network.config.to_dict(),
                mode_status=mode_status,
                tunnel=tunnel if isinstance(tunnel, dict) else None,
            )
        )

    @app.get("/network", include_in_schema=False)
    async def network_landing_alias(request: Request):
        return await network_landing(request)

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


def _render_network_landing(
    *,
    enabled: bool,
    available: bool,
    state: str,
    detail: str,
    config: dict[str, object] | None,
    mode_status: dict[str, object] | None = None,
    tunnel: dict[str, object] | None = None,
) -> str:
    """Render the small Phase 7/8 phone entry point without frontend assets."""

    safe_state = escape(state.replace("-", " ").title())
    safe_state_class = escape(state.lower())
    safe_detail = escape(detail)
    if config is None:
        address = "unavailable"
        hostname = "unavailable"
        app_url = "/"
    else:
        address = escape(str(config["address"]))
        hostname = escape(str(config["hostname"]))
        app_url = "/"
    mode = str((mode_status or {}).get("mode") or "SOLO")
    pairing = (mode_status or {}).get("pairing")
    tunnel_enabled = bool(tunnel and tunnel.get("enabled"))
    tunnel_ready = tunnel_enabled and tunnel.get("state") == "ready"
    if tunnel_enabled and mode == "NETWORKED_UNPAIRED" and tunnel_ready:
        headline = "Networked mode is ready to pair"
        note = "Scan the HTTPS QR code on the Pi screen or open the secure link below."
    elif tunnel_enabled and tunnel.get("state") == "starting":
        headline = "Secure Botanika link is starting"
        note = "The Pi is setting up a temporary HTTPS connection; refresh in a few seconds."
    elif tunnel_enabled and tunnel.get("state") == "failed":
        headline = "Secure Botanika link could not start"
        note = "The Pi operator can retry the local tunnel or return to SOLO."
    elif not enabled and not tunnel_enabled:
        headline = "SOLO mode is active"
        note = "The private Wi-Fi link is disabled. The Pi kiosk remains available on loopback."
    elif mode == "NETWORKED_UNPAIRED":
        headline = "Networked mode is ready to pair"
        note = "Join the private Wi-Fi, open Botanika, and enter the one-time code shown on the Pi."
    elif mode == "NETWORKED_PAIRED":
        headline = "A Botanika controller is paired"
        note = "The Pi screen is now a status console. The active browser owns the controller lease."
    elif available:
        headline = "Private Botanika link is ready"
        note = "This page is served locally by the Pi; internet access is not required."
    else:
        headline = "Private Botanika link is starting"
        note = "The access point is configured but one or more local checks have not passed."
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Botanika · Private Pi link</title>
    <style>
      :root {{ color-scheme: light; font-family: system-ui, sans-serif; background: #efede3; color: #272724; }}
      body {{ box-sizing: border-box; margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 1.25rem; background-image: linear-gradient(#e2dfd5 1px, transparent 1px), linear-gradient(90deg, #e2dfd5 1px, transparent 1px); background-size: 28px 28px; }}
      main {{ width: min(34rem, 100%); background: #f7f4e9; border: 1px solid #272724; padding: 1.5rem; box-shadow: 0 18px 42px rgba(39, 39, 36, .13); }}
      h1 {{ font: 2rem Georgia, serif; margin: 0 0 .25rem; }}
      h2 {{ font-size: 1rem; margin: 1.4rem 0 .35rem; }}
      p {{ line-height: 1.45; }}
      .status {{ border-left: .3rem solid #486b51; background: #e2dfd5; padding: .7rem .8rem; }}
      .status.degraded, .status.unavailable {{ border-left-color: #8a692e; }}
      dl {{ display: grid; grid-template-columns: max-content 1fr; gap: .35rem .8rem; }}
      dt {{ color: #5f5e59; }} dd {{ margin: 0; overflow-wrap: anywhere; }}
      a {{ display: inline-block; margin-top: 1rem; padding: .75rem 1rem; border: 1px solid #272724; color: #f7f4e9; background: #41413d; text-decoration: none; }}
      small {{ color: #5f5e59; }}
    </style>
  </head>
  <body>
    <main>
      <h1>Botanika</h1>
      <p><strong>{escape(headline)}</strong><br>{escape(note)}</p>
      <section class="status {safe_state_class}" aria-live="polite">
        <strong>Transport: {safe_state}</strong>
        <div>{safe_detail}</div>
      </section>
      {f'<h2>Secure link</h2><dl><dt>Quick Tunnel</dt><dd>{escape(str(tunnel.get("connect_url") or tunnel.get("url") or "starting"))}</dd></dl>' if tunnel_enabled else ''}
      <h2>Local address</h2>
      <dl>
        <dt>AP address</dt><dd>{address}</dd>
        <dt>Hostname</dt><dd>{hostname}</dd>
      </dl>
      {f'<h2>Pairing code</h2><p><strong class="code">{escape(str(pairing.get("code")))}</strong><br><small>Expires in {escape(str(pairing.get("expires_in_seconds", "–")))} seconds · single use</small></p>' if isinstance(pairing, dict) and pairing.get("code") else ''}
      <a href="{app_url}">Open Botanika</a>
      <p><small>Phase 8 uses one short-lived controller lease. The Pi remains the authoritative classifier and library.</small></p>
    </main>
  </body>
</html>"""
