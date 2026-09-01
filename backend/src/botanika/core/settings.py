"""Environment-backed settings for the Pi service.

The defaults are deliberately useful for local development. Production should
set ``BOTANIKA_ENVIRONMENT=production`` and provide the Cloudflare Access
audience/team settings in the service environment file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


@dataclass(frozen=True)
class Settings:
    app_name: str = "Botanika"
    app_version: str = "0.1.0"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    # The request envelope is slightly larger than the image cap so a 5 MiB
    # image can carry multipart headers and the small metadata field.
    max_request_bytes: int = 6 * 1024 * 1024
    max_image_bytes: int = 5 * 1024 * 1024
    max_image_pixels: int = 20_000_000
    max_image_dimension: int = 8192
    idempotency_ttl_seconds: int = 600
    idempotency_cache_size: int = 256
    receipt_rate_limit: int = 30
    receipt_rate_window_seconds: int = 60
    websocket_heartbeat_seconds: int = 20
    frontend_dir: Path = Path("frontend")
    temporary_dir: Path = Path("data/media/temp")
    access_required: bool = False
    access_team_domain: str | None = None
    access_jwks_url: str | None = None
    access_audience: str | None = None
    access_allowed_email: str = "kisoreabhinav@gmail.com"
    csrf_required: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        environment = os.getenv("BOTANIKA_ENVIRONMENT", "development").strip()
        repository_root = Path(__file__).resolve().parents[4]
        default_frontend = repository_root / "frontend"
        default_temporary = repository_root / "data" / "media" / "temp"
        access_required = _env_bool(
            "BOTANIKA_ACCESS_REQUIRED", environment.lower() in {"production", "prod"}
        )
        frontend_dir = Path(os.getenv("BOTANIKA_FRONTEND_DIR", str(default_frontend)))
        temporary_dir = Path(
            os.getenv("BOTANIKA_TEMPORARY_DIR", str(default_temporary))
        )
        team_domain = os.getenv("CLOUDFLARE_ACCESS_TEAM_DOMAIN")
        if team_domain:
            team_domain = team_domain.strip().rstrip("/")
        jwks_url = os.getenv("CLOUDFLARE_ACCESS_JWKS_URL")
        if not jwks_url and team_domain:
            jwks_url = f"{team_domain.rstrip('/')}/cdn-cgi/access/certs"

        return cls(
            app_name=os.getenv("BOTANIKA_APP_NAME", "Botanika"),
            app_version=os.getenv("BOTANIKA_APP_VERSION", "0.1.0"),
            environment=environment,
            host=os.getenv("BOTANIKA_HOST", "127.0.0.1"),
            port=_env_int("BOTANIKA_PORT", 8000),
            max_request_bytes=_env_int(
                "BOTANIKA_MAX_REQUEST_BYTES", 6 * 1024 * 1024
            ),
            max_image_bytes=_env_int("BOTANIKA_MAX_IMAGE_BYTES", 5 * 1024 * 1024),
            max_image_pixels=_env_int("BOTANIKA_MAX_IMAGE_PIXELS", 20_000_000),
            max_image_dimension=_env_int("BOTANIKA_MAX_IMAGE_DIMENSION", 8192),
            idempotency_ttl_seconds=_env_int(
                "BOTANIKA_IDEMPOTENCY_TTL_SECONDS", 600
            ),
            idempotency_cache_size=_env_int("BOTANIKA_IDEMPOTENCY_CACHE_SIZE", 256),
            receipt_rate_limit=_env_int("BOTANIKA_RECEIPT_RATE_LIMIT", 30),
            receipt_rate_window_seconds=_env_int(
                "BOTANIKA_RECEIPT_RATE_WINDOW_SECONDS", 60
            ),
            websocket_heartbeat_seconds=_env_int(
                "BOTANIKA_WS_HEARTBEAT_SECONDS", 20
            ),
            frontend_dir=frontend_dir,
            temporary_dir=temporary_dir,
            access_required=access_required,
            access_team_domain=team_domain,
            access_jwks_url=jwks_url,
            access_audience=os.getenv("CLOUDFLARE_ACCESS_AUDIENCE"),
            access_allowed_email=os.getenv(
                "BOTANIKA_ACCESS_ALLOWED_EMAIL", "kisoreabhinav@gmail.com"
            ).strip().lower(),
            csrf_required=_env_bool("BOTANIKA_CSRF_REQUIRED", access_required),
        )
