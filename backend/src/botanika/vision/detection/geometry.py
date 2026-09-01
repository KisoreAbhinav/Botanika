"""Coordinate geometry shared by the detector and its display runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """An xyxy box in a known image coordinate system."""

    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def height(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.width * self.height

    def clamp(self, width: int, height: int) -> "BoundingBox":
        return BoundingBox(
            max(0.0, min(float(width), self.x1)),
            max(0.0, min(float(height), self.y1)),
            max(0.0, min(float(width), self.x2)),
            max(0.0, min(float(height), self.y2)),
        )


@dataclass(frozen=True, slots=True)
class LetterboxTransform:
    """Map source coordinates to a padded detector input and back."""

    source_width: int
    source_height: int
    target_width: int
    target_height: int
    scale: float
    pad_left: int
    pad_top: int
    resized_width: int
    resized_height: int

    @classmethod
    def for_image(
        cls,
        source_width: int,
        source_height: int,
        target_width: int,
        target_height: int,
    ) -> "LetterboxTransform":
        if min(source_width, source_height, target_width, target_height) <= 0:
            raise ValueError("image dimensions must be positive")
        scale = min(target_width / source_width, target_height / source_height)
        resized_width = max(1, round(source_width * scale))
        resized_height = max(1, round(source_height * scale))
        return cls(
            source_width=source_width,
            source_height=source_height,
            target_width=target_width,
            target_height=target_height,
            scale=scale,
            pad_left=(target_width - resized_width) // 2,
            pad_top=(target_height - resized_height) // 2,
            resized_width=resized_width,
            resized_height=resized_height,
        )

    def to_input_box(self, box: BoundingBox) -> BoundingBox:
        return BoundingBox(
            box.x1 * self.scale + self.pad_left,
            box.y1 * self.scale + self.pad_top,
            box.x2 * self.scale + self.pad_left,
            box.y2 * self.scale + self.pad_top,
        )

    def to_source_box(self, box: BoundingBox) -> BoundingBox:
        return BoundingBox(
            (box.x1 - self.pad_left) / self.scale,
            (box.y1 - self.pad_top) / self.scale,
            (box.x2 - self.pad_left) / self.scale,
            (box.y2 - self.pad_top) / self.scale,
        ).clamp(self.source_width, self.source_height)


@dataclass(frozen=True, slots=True)
class DisplayTransform:
    """Map a source frame into a fixed display canvas without distortion."""

    source_width: int
    source_height: int
    display_width: int
    display_height: int
    scale: float
    offset_x: int
    offset_y: int
    rendered_width: int
    rendered_height: int

    def to_display_box(self, box: BoundingBox) -> BoundingBox:
        return BoundingBox(
            box.x1 * self.scale + self.offset_x,
            box.y1 * self.scale + self.offset_y,
            box.x2 * self.scale + self.offset_x,
            box.y2 * self.scale + self.offset_y,
        ).clamp(self.display_width, self.display_height)


def fit_frame_to_window(
    frame: np.ndarray,
    display_width: int,
    display_height: int,
    *,
    cv2_module: Any = cv2,
) -> tuple[np.ndarray, DisplayTransform]:
    """Letterbox a BGR frame into a fixed display canvas and return its map."""

    if frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"expected a 3-channel frame, got {frame.shape!r}")
    source_height, source_width = frame.shape[:2]
    transform = DisplayTransform(
        source_width=source_width,
        source_height=source_height,
        display_width=display_width,
        display_height=display_height,
        scale=min(display_width / source_width, display_height / source_height),
        offset_x=0,
        offset_y=0,
        rendered_width=0,
        rendered_height=0,
    )
    rendered_width = max(1, round(source_width * transform.scale))
    rendered_height = max(1, round(source_height * transform.scale))
    offset_x = (display_width - rendered_width) // 2
    offset_y = (display_height - rendered_height) // 2
    transform = DisplayTransform(
        source_width=source_width,
        source_height=source_height,
        display_width=display_width,
        display_height=display_height,
        scale=transform.scale,
        offset_x=offset_x,
        offset_y=offset_y,
        rendered_width=rendered_width,
        rendered_height=rendered_height,
    )
    rendered = cv2_module.resize(
        frame,
        (rendered_width, rendered_height),
        interpolation=cv2_module.INTER_AREA,
    )
    canvas = np.zeros((display_height, display_width, 3), dtype=frame.dtype)
    canvas[
        offset_y : offset_y + rendered_height,
        offset_x : offset_x + rendered_width,
    ] = rendered
    return canvas, transform
