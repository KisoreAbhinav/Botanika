"""Reusable scan coordination services for the Phase 6 kiosk."""

from .events import EventHub
from .overlay import BoxLike, OverlayTransform
from .preview import (
    PreviewBuffer,
    PreviewFrame,
    encode_jpeg,
    letterbox_frame,
    placeholder_frame,
)
from .scan import FallbackImage, ScanService
from .snapshot import ScanSnapshot, snapshot_from_update

__all__ = [
    "BoxLike",
    "EventHub",
    "FallbackImage",
    "OverlayTransform",
    "PreviewBuffer",
    "PreviewFrame",
    "ScanService",
    "ScanSnapshot",
    "encode_jpeg",
    "letterbox_frame",
    "placeholder_frame",
    "snapshot_from_update",
]
