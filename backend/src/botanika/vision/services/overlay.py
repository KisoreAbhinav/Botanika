"""Source-frame to preview-canvas overlay mapping for the kiosk Scan screen.

The backend owns the camera and renders every preview frame letterboxed into a
fixed ``preview_width x preview_height`` canvas.  Each published event carries
one of these transforms so the browser can place detector boxes exactly over the
rendered video rectangle without re-deriving letterbox geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class BoxLike(Protocol):
    """Any object exposing the four xyxy attributes used by the mapping."""

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True, slots=True)
class OverlayTransform:
    """Mapping between source frame coordinates and the preview canvas."""

    source_width: int
    source_height: int
    preview_width: int
    preview_height: int
    scale: float
    offset_x: int
    offset_y: int
    rendered_width: int
    rendered_height: int

    @classmethod
    def for_frame(
        cls,
        source_width: int,
        source_height: int,
        preview_width: int,
        preview_height: int,
    ) -> "OverlayTransform":
        """Compute a contain-fit letterbox mapping with integer offsets."""

        if min(source_width, source_height, preview_width, preview_height) <= 0:
            raise ValueError("image and preview dimensions must be positive")
        scale = min(preview_width / source_width, preview_height / source_height)
        rendered_width = max(1, round(source_width * scale))
        rendered_height = max(1, round(source_height * scale))
        return cls(
            source_width=source_width,
            source_height=source_height,
            preview_width=preview_width,
            preview_height=preview_height,
            scale=scale,
            offset_x=(preview_width - rendered_width) // 2,
            offset_y=(preview_height - rendered_height) // 2,
            rendered_width=rendered_width,
            rendered_height=rendered_height,
        )

    def to_preview_box(self, box: "BoxLike") -> tuple[float, float, float, float]:
        """Map an xyxy box in source coordinates to preview-canvas coordinates."""

        return (
            box.x1 * self.scale + self.offset_x,
            box.y1 * self.scale + self.offset_y,
            box.x2 * self.scale + self.offset_x,
            box.y2 * self.scale + self.offset_y,
        )

    def clamp_preview(self, values: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        return (
            max(0.0, min(float(self.preview_width), values[0])),
            max(0.0, min(float(self.preview_height), values[1])),
            max(0.0, min(float(self.preview_width), values[2])),
            max(0.0, min(float(self.preview_height), values[3])),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_width": self.source_width,
            "source_height": self.source_height,
            "preview_width": self.preview_width,
            "preview_height": self.preview_height,
            "scale": self.scale,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "rendered_width": self.rendered_width,
            "rendered_height": self.rendered_height,
        }