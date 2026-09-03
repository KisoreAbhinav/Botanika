"""Botanika's local application core: settings, errors, and capabilities."""

from .capabilities import CapabilitiesReport, CapabilityState, build_capabilities, empty_capabilities
from .errors import (
    BotanikaError,
    CapabilityUnavailableError,
    NotFoundError,
    ProblemDetail,
    ValidationError,
)
from .settings import (
    AppSettings,
    BACKEND_SOURCE,
    DEFAULT_MANIFEST,
    DEFAULT_QUALITY_CONFIG,
    DEFAULT_SQLITE_PATH,
    FRONTEND_DIST,
    PROJECT_ROOT,
)

__all__ = [
    "AppSettings",
    "BACKEND_SOURCE",
    "BotanikaError",
    "CapabilitiesReport",
    "CapabilityState",
    "CapabilityUnavailableError",
    "DEFAULT_MANIFEST",
    "DEFAULT_QUALITY_CONFIG",
    "DEFAULT_SQLITE_PATH",
    "FRONTEND_DIST",
    "NotFoundError",
    "PROJECT_ROOT",
    "ProblemDetail",
    "ValidationError",
    "build_capabilities",
    "empty_capabilities",
]