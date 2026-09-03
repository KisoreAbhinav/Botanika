#!/usr/bin/env python3
"""Serve the Botanika Phase 6 modular monolith on loopback.

Starts FastAPI with the built kiosk frontend, the scan pipeline, offline
knowledge store, and species-grouped library in one process. The service binds
to 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

# Allow the script to run directly from a source checkout without installation.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

import uvicorn

from botanika.api import create_app
from botanika.api.runtime import APP_VERSION
from botanika.core.settings import FRONTEND_DIST, AppSettings

LOGGER = logging.getLogger("botanika.phase6")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000, help="loopback port (default: 8000)")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address; Phase 6 keeps the service on loopback (default: 127.0.0.1)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = build_parser().parse_args(argv)
    settings = AppSettings(host=args.host, port=args.port)

    print(
        f"Botanika {APP_VERSION} starting on http://{settings.host}:{settings.port}",
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

    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
