"""Crop-only transient capture storage for Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import time
from typing import Callable

import cv2
import numpy as np

from ..detection.geometry import BoundingBox


@dataclass(frozen=True, slots=True)
class CaptureResult:
    """Metadata for a crop file, including duplicate-save outcomes."""

    path: Path | None
    crop_box: BoundingBox
    width: int
    height: int
    content_hash: str
    duplicate: bool = False
    manual: bool = False


class CropStore:
    """Write only the padded candidate crop; never serialize the source frame."""

    def __init__(
        self,
        output_dir: Path,
        *,
        padding_ratio: float = 0.08,
        deduplication_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if padding_ratio < 0 or padding_ratio > 1:
            raise ValueError("padding_ratio must be between 0 and 1")
        if deduplication_seconds < 0:
            raise ValueError("deduplication_seconds must not be negative")
        self.output_dir = output_dir
        self.padding_ratio = padding_ratio
        self.deduplication_seconds = deduplication_seconds
        self._clock = clock
        self._last_hash: str | None = None
        self._last_saved_at: float | None = None
        self._sequence = 0

    def save(
        self,
        frame: np.ndarray,
        source_box: BoundingBox,
        *,
        manual: bool = False,
    ) -> CaptureResult:
        """Encode and persist a PNG made from the candidate crop only."""

        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(f"expected a 3-channel BGR frame, got {getattr(frame, 'shape', None)!r}")
        frame_height, frame_width = frame.shape[:2]
        crop_box = _padded_box(source_box, self.padding_ratio).clamp(frame_width, frame_height)
        x1 = max(0, min(frame_width - 1, math.floor(crop_box.x1)))
        y1 = max(0, min(frame_height - 1, math.floor(crop_box.y1)))
        x2 = max(x1 + 1, min(frame_width, math.ceil(crop_box.x2)))
        y2 = max(y1 + 1, min(frame_height, math.ceil(crop_box.y2)))
        exact_crop_box = BoundingBox(float(x1), float(y1), float(x2), float(y2))
        crop = np.ascontiguousarray(frame[y1:y2, x1:x2])
        encoded_ok, encoded = cv2.imencode(".png", crop)
        if not encoded_ok:
            raise OSError("OpenCV could not encode the candidate crop")
        encoded_bytes = encoded.tobytes()
        content_hash = hashlib.sha256(encoded_bytes).hexdigest()
        now = self._clock()
        if (
            self._last_hash == content_hash
            and self._last_saved_at is not None
            and now - self._last_saved_at <= self.deduplication_seconds
        ):
            return CaptureResult(
                path=None,
                crop_box=exact_crop_box,
                width=x2 - x1,
                height=y2 - y1,
                content_hash=content_hash,
                duplicate=True,
                manual=manual,
            )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._sequence += 1
        path = self.output_dir / f"crop-{self._sequence:06d}-{content_hash[:12]}.png"
        path.write_bytes(encoded_bytes)
        self._last_hash = content_hash
        self._last_saved_at = now
        return CaptureResult(
            path=path,
            crop_box=exact_crop_box,
            width=x2 - x1,
            height=y2 - y1,
            content_hash=content_hash,
            manual=manual,
        )

    def save_external(
        self,
        encoded_bytes: bytes,
        image: np.ndarray,
        *,
        manual: bool = True,
    ) -> CaptureResult:
        """Persist one validated browser crop without padding or re-encoding.

        The browser has already performed crop construction and local quality
        checks.  Keeping the uploaded encoded bytes unchanged makes the hash
        and dimensions auditable before and after the HTTP handoff.  Only this
        crop is written; a browser video frame is never accepted by this API.
        """

        if not isinstance(encoded_bytes, (bytes, bytearray)) or not encoded_bytes:
            raise ValueError("external crop bytes must be non-empty")
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError(f"expected a 3-channel BGR crop, got {getattr(image, 'shape', None)!r}")
        if image.dtype != np.uint8 or min(image.shape[:2]) < 3:
            raise ValueError("external crop must be a non-empty uint8 image")
        encoded = bytes(encoded_bytes)
        content_hash = hashlib.sha256(encoded).hexdigest()
        height, width = image.shape[:2]
        now = self._clock()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._sequence += 1
        path = self.output_dir / f"remote-{self._sequence:06d}-{content_hash[:12]}.png"
        path.write_bytes(encoded)
        if not path.is_file() or path.stat().st_size != len(encoded):
            path.unlink(missing_ok=True)
            raise OSError("external crop could not be verified")
        self._last_hash = content_hash
        self._last_saved_at = now
        return CaptureResult(
            path=path,
            crop_box=BoundingBox(0.0, 0.0, float(width), float(height)),
            width=width,
            height=height,
            content_hash=content_hash,
            manual=manual,
        )

    def discard(self, capture: CaptureResult | None) -> None:
        """Best-effort removal of a transient crop after a newer request."""

        if capture is None or capture.path is None:
            return
        try:
            capture.path.unlink(missing_ok=True)
        except OSError:
            pass


def _padded_box(box: BoundingBox, padding_ratio: float) -> BoundingBox:
    pad_x = box.width * padding_ratio
    pad_y = box.height * padding_ratio
    return BoundingBox(box.x1 - pad_x, box.y1 - pad_y, box.x2 + pad_x, box.y2 + pad_y)
