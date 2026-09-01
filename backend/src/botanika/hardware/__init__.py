"""Hardware ownership adapters for Botanika."""

from .camera import (
    CameraConfig,
    CameraError,
    CameraOpenError,
    CameraFrame,
    CameraOwner,
    CameraStateError,
    FrameReadError,
    convert_rgb_to_bgr,
)

__all__ = [
    "CameraConfig",
    "CameraError",
    "CameraOpenError",
    "CameraFrame",
    "CameraOwner",
    "CameraStateError",
    "FrameReadError",
    "convert_rgb_to_bgr",
]
