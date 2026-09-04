"""Independent multi-box weed-beta detector and crop-only service."""

from .service import (
    WeedDetection,
    WeedDetectorManifest,
    WeedService,
    WeedServiceStatus,
    WeedUnavailable,
)

__all__ = [
    "WeedDetection",
    "WeedDetectorManifest",
    "WeedService",
    "WeedServiceStatus",
    "WeedUnavailable",
]
