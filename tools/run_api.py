#!/usr/bin/env python3
"""Serve the Botanika Phase 9 modular monolith in SOLO, AP, or tunnel mode.

Starts FastAPI with the built kiosk frontend, the scan pipeline, offline
knowledge/voice/weed services, species-grouped library, and mode handoff in one
process. The service binds to loopback in SOLO and Quick Tunnel mode. Phase 7
network mode uses a wildcard listener and relies on the installed AP-only
firewall unit to preserve both loopback and private Wi-Fi reachability.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import logging
from pathlib import Path
import sys

# Allow the script to run directly from a source checkout without installation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import FRONTEND_DIST, AppSettings
from botanika.network import AccessPointConfig, NetworkStatusProbe

LOGGER = logging.getLogger("botanika.phase9")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--network",
        action="store_true",
        help="serve the same app for the private access point and loopback",
    )
    mode.add_argument(
        "--solo",
        action="store_true",
        help="force loopback-only SOLO mode, even if the environment enables networking",
    )
    parser.add_argument("--port", type=int, default=None, help="API port (default: 8000)")
    parser.add_argument(
        "--host",
        default=None,
        help="bind address; SOLO defaults to 127.0.0.1 and network mode to 0.0.0.0",
    )
    parser.add_argument("--interface", default=None, help="private AP interface override")
    parser.add_argument("--ap-address", default=None, help="private AP IPv4 address override")
    parser.add_argument("--hostname", default=None, help="local DNS hostname override")
    return parser


def main(argv: list[str] | None = None) -> int:
    from botanika.api import create_app
    from botanika.api.runtime import APP_VERSION

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    settings = AppSettings.from_environment()
    if args.network:
        settings = replace(
            settings,
            network_enabled=True,
            loopback_only=False,
            host=args.host or (settings.host if settings.host != "127.0.0.1" else "0.0.0.0"),
        )
    elif args.solo:
        settings = replace(
            settings,
            network_enabled=False,
            loopback_only=True,
            host=args.host or "127.0.0.1",
        )
    elif args.host is not None:
        settings = replace(settings, host=args.host)
    if args.port is not None:
        settings = replace(settings, port=args.port)
    if args.interface is not None:
        settings = replace(settings, access_point_interface=args.interface)
    if args.ap_address is not None:
        settings = replace(settings, access_point_address=args.ap_address)
    if args.hostname is not None:
        settings = replace(settings, local_hostname=args.hostname)
    settings = resolve_safe_bind(settings)

    print(
        f"Botanika {APP_VERSION} starting on http://{settings.host}:{settings.port}",
        flush=True,
    )
    if settings.network_enabled:
        print(
            "Private AP URL: "
            f"http://{settings.access_point_address}:{settings.port}/connect "
            f"({settings.local_hostname})",
            flush=True,
        )
    if settings.tunnel_enabled:
        print(
            "Cloudflare Quick Tunnel enabled; select NETWORKED on the Pi to publish an HTTPS URL.",
            flush=True,
        )
    if FRONTEND_DIST.is_dir():
        print(f"Serving the built kiosk from {FRONTEND_DIST}", flush=True)
    else:
        print(
            "Frontend build not found; the API will answer but '/' shows a build hint. "
            "Run `npm run build` inside frontend/.",
            flush=True,
        )

    import uvicorn

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    return 0


def resolve_safe_bind(
    settings: AppSettings,
    *,
    probe: NetworkStatusProbe | None = None,
) -> AppSettings:
    """Open the wildcard listener only behind a measured AP boundary.

    AP intent remains enabled in fallback mode so readiness and the kiosk can
    honestly report that networking is degraded while SOLO stays usable.
    """

    if not settings.network_enabled or settings.loopback_only:
        return settings
    active_probe = probe or NetworkStatusProbe(AccessPointConfig.from_settings(settings))
    checks = active_probe.boundary_checks()
    if all(checks.values()):
        return settings
    missing = ", ".join(name for name, passed in checks.items() if not passed)
    LOGGER.error(
        "Private AP boundary is incomplete (%s); falling back to loopback without disabling AP health reporting",
        missing,
    )
    return replace(settings, host="127.0.0.1", loopback_only=True)


if __name__ == "__main__":
    raise SystemExit(main())
