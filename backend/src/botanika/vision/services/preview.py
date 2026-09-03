"""Backend-owned preview frames for the local MJPEG stream."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Callable

import cv2
import numpy as np

from .overlay import OverlayTransform


@dataclass(frozen=True, slots=True)
class PreviewFrame:
    """One letterboxed, JPEG-encoded preview frame plus its transform."""

    sequence: int
    captured_at: float
    source_sequence: int | None
    transform: OverlayTransform
    jpeg_bytes: bytes

    @property
    def width(self) -> int:
        return self.transform.preview_width

    @property
    def height(self) -> int:
        return self.transform.preview_height

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "captured_at": self.captured_at,
            "source_sequence": self.source_sequence,
            "transform": self.transform.to_dict(),
        }


def encode_jpeg(frame: np.ndarray, quality: int = 72) -> bytes:
    """Encode a BGR frame as JPEG bytes with explicit quality control."""

    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"expected a 3-channel BGR frame, got {getattr(frame, 'shape', None)!r}")
    encoded_ok, encoded = cv2.imencode(
        ".jpg",
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, int(max(1, min(100, quality)))],
    )
    if not encoded_ok:
        raise OSError("OpenCV could not encode the preview frame")
    return encoded.tobytes()


def letterbox_frame(frame: np.ndarray, transform: OverlayTransform) -> np.ndarray:
    """Resize and centre a source frame onto the preview canvas (black bars)."""

    rendered = cv2.resize(
        frame,
        (transform.rendered_width, transform.rendered_height),
        interpolation=cv2.INTER_AREA,
    )
    canvas = np.zeros(
        (transform.preview_height, transform.preview_width, 3),
        dtype=frame.dtype,
    )
    canvas[
        transform.offset_y : transform.offset_y + transform.rendered_height,
        transform.offset_x : transform.offset_x + transform.rendered_width,
    ] = rendered
    return canvas


def placeholder_frame(
    transform: OverlayTransform,
    *,
    message: str = "Waiting for a camera frame",
    encode: Callable[[np.ndarray, int], bytes] = encode_jpeg,
) -> PreviewFrame:
    """Return a deterministic black placeholder so the stream is never empty."""

    canvas = np.zeros((transform.preview_height, transform.preview_width, 3), dtype=np.uint8)
    cv2.putText(
        canvas,
        message,
        (18, transform.preview_height // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.5,
        (120, 120, 120),
        1,
        cv2.LINE_AA,
    )
    return PreviewFrame(
        sequence=0,
        captured_at=0.0,
        source_sequence=None,
        transform=transform,
        jpeg_bytes=encode(canvas, 72),
    )


class PreviewBuffer:
    """Thread-safe single-slot store of the latest preview frame.

    Only the newest frame is kept: consumers that are slower than the camera
    always render the freshest state rather than an unbounded backlog.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: PreviewFrame | None = None

    def put(self, frame: PreviewFrame) -> None:
        with self._lock:
            self._latest = frame

    def get(self) -> PreviewFrame | None:
        with self._lock:
            return self._latest

    def sequence(self) -> int:
        with self._lock:
            return self._latest.sequence if self._latest is not None else 0