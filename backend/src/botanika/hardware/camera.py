"""Single-owner Picamera2 adapter used by the Phase 1 raw-feed runner.

This module deliberately knows nothing about FastAPI, the browser UI, models,
or persistence. It owns one Picamera2 instance, exposes OpenCV-compatible BGR
frames, and makes shutdown safe when startup or capture fails.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable, Protocol

import cv2
import numpy as np


class CameraError(RuntimeError):
    """Base error for camera lifecycle and frame acquisition failures."""


class CameraOpenError(CameraError):
    """Raised when the camera cannot be configured or started."""


class CameraStateError(CameraError):
    """Raised when a frame is requested outside the running state."""


class FrameReadError(CameraError):
    """Raised when a captured frame is missing or has an invalid shape."""


@dataclass(frozen=True, slots=True)
class CameraConfig:
    """Validated stream and display settings for the raw camera feed."""

    width: int = 1536
    height: int = 864
    fps: int = 30
    window_width: int = 800
    window_height: int = 480
    window_name: str = "Botanika Camera"

    def __post_init__(self) -> None:
        for field_name in (
            "width",
            "height",
            "fps",
            "window_width",
            "window_height",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if not self.window_name.strip():
            raise ValueError("window_name must not be empty")

    @property
    def main_stream(self) -> dict[str, Any]:
        """Return the Picamera2 stream contract used by this phase."""

        return {
            "size": (self.width, self.height),
            "format": "RGB888",
        }

    def preview_configuration(self) -> dict[str, Any]:
        """Return arguments for ``create_preview_configuration``."""

        return {
            "main": self.main_stream,
            "controls": {"FrameRate": float(self.fps)},
        }


@dataclass(frozen=True, slots=True)
class CameraFrame:
    """One OpenCV BGR frame and its local monotonic timestamp."""

    image: np.ndarray
    captured_at: float
    sequence: int


class PicameraLike(Protocol):
    """Small portion of Picamera2 used by ``CameraOwner``."""

    def create_preview_configuration(self, **kwargs: Any) -> Any: ...

    def configure(self, configuration: Any) -> Any: ...

    def start(self) -> Any: ...

    def capture_array(self, name: str = "main") -> np.ndarray: ...

    def stop(self) -> Any: ...

    def close(self) -> Any: ...


def default_camera_factory() -> PicameraLike:
    """Construct Picamera2 lazily so non-Pi unit tests can import this module."""

    try:
        from picamera2 import Picamera2
    except Exception as exc:  # Native import errors should be user-visible.
        raise CameraOpenError(
            "Picamera2 is unavailable; check the Phase 0 native camera setup"
        ) from exc
    return Picamera2()


def convert_rgb_to_bgr(frame: np.ndarray) -> np.ndarray:
    """Convert a Picamera2 RGB888 array to the BGR layout OpenCV expects."""

    if not isinstance(frame, np.ndarray):
        raise FrameReadError("camera returned a non-array frame")
    if frame.ndim != 3 or frame.shape[2] != 3:
        raise FrameReadError(
            f"camera returned an unexpected frame shape: {frame.shape!r}"
        )
    return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)


class CameraOwner:
    """Own one camera handle and publish sequential OpenCV-compatible frames."""

    def __init__(
        self,
        config: CameraConfig | None = None,
        camera_factory: Callable[[], PicameraLike] = default_camera_factory,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or CameraConfig()
        self._camera_factory = camera_factory
        self._clock = clock
        self._camera: PicameraLike | None = None
        self._running = False
        self._sequence = 0
        self.frames_read = 0
        self.dropped_frames = 0

    @property
    def is_running(self) -> bool:
        return self._running

    def open(self) -> None:
        """Configure and start the camera, cleaning up partial startup."""

        if self._running:
            return

        camera: PicameraLike | None = None
        try:
            camera = self._camera_factory()
            configuration = camera.create_preview_configuration(
                **self.config.preview_configuration()
            )
            camera.configure(configuration)
            camera.start()
        except Exception as exc:
            self._cleanup_camera(camera)
            raise CameraOpenError(f"could not open the Pi Camera: {exc}") from exc

        self._camera = camera
        self._running = True
        self._sequence = 0
        self.frames_read = 0
        self.dropped_frames = 0

    def read(self) -> CameraFrame:
        """Capture and convert one frame; count failed reads as dropped frames."""

        if not self._running or self._camera is None:
            raise CameraStateError("camera is not running")

        try:
            rgb_frame = self._camera.capture_array("main")
            bgr_frame = convert_rgb_to_bgr(rgb_frame)
        except Exception as exc:
            self.dropped_frames += 1
            if isinstance(exc, FrameReadError):
                raise
            raise FrameReadError(f"could not read a camera frame: {exc}") from exc

        self._sequence += 1
        self.frames_read += 1
        return CameraFrame(
            image=bgr_frame,
            captured_at=self._clock(),
            sequence=self._sequence,
        )

    def close(self) -> None:
        """Stop and close the camera, attempting both steps on every exit path."""

        camera = self._camera
        self._camera = None
        self._running = False
        self._cleanup_camera(camera)

    @staticmethod
    def _cleanup_camera(camera: PicameraLike | None) -> None:
        if camera is None:
            return
        try:
            camera.stop()
        except Exception:
            # A failed stop must not prevent close from releasing the device.
            pass
        try:
            camera.close()
        except Exception:
            pass

    def __enter__(self) -> "CameraOwner":
        self.open()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

