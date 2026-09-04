"""Hardware ownership adapters for Botanika."""

from .camera import (
    CameraConfig,
    CameraError,
    CameraOpenError,
    CameraFrame,
    CameraOwner,
    CameraStateError,
    FrameReadError,
    picamera_rgb888_to_opencv_bgr,
)
from .gpio import (
    GPIOBackend,
    GPIOPinConfig,
    MemoryGPIO,
    ModeGPIOAdapter,
    NullGPIO,
    RPiGPIOBackend,
    SoftwareModeFallback,
    create_mode_gpio,
)

__all__ = [
    "CameraConfig",
    "CameraError",
    "CameraOpenError",
    "CameraFrame",
    "CameraOwner",
    "CameraStateError",
    "FrameReadError",
    "picamera_rgb888_to_opencv_bgr",
    "GPIOBackend",
    "GPIOPinConfig",
    "MemoryGPIO",
    "ModeGPIOAdapter",
    "NullGPIO",
    "RPiGPIOBackend",
    "SoftwareModeFallback",
    "create_mode_gpio",
]
