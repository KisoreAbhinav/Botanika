"""Focus, exposure, size, and edge checks for one candidate crop."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

import cv2
import numpy as np

from ..detection.geometry import BoundingBox


@dataclass(frozen=True, slots=True)
class QualityConfig:
    """Configurable Phase 3 baseline; values require Pi-scene calibration."""

    min_target_width: int = 80
    min_target_height: int = 80
    min_laplacian_variance: float = 100.0
    min_mean_luma: float = 25.0
    max_mean_luma: float = 235.0
    max_saturated_fraction: float = 0.08
    edge_margin_ratio: float = 0.01

    @classmethod
    def from_file(cls, path: Path) -> "QualityConfig":
        """Load thresholds while leaving calibration metadata outside the contract."""

        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ValueError(f"quality config not found: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read quality config {path}: {exc}") from exc
        fields = {
            "min_target_width",
            "min_target_height",
            "min_laplacian_variance",
            "min_mean_luma",
            "max_mean_luma",
            "max_saturated_fraction",
            "edge_margin_ratio",
        }
        return cls(**{field: values[field] for field in fields if field in values})

    def __post_init__(self) -> None:
        if self.min_target_width <= 0 or self.min_target_height <= 0:
            raise ValueError("minimum target dimensions must be positive")
        if self.min_laplacian_variance < 0:
            raise ValueError("min_laplacian_variance must not be negative")
        if not 0 <= self.min_mean_luma < self.max_mean_luma <= 255:
            raise ValueError("luma bounds must be ordered within 0..255")
        if not 0 <= self.max_saturated_fraction <= 1:
            raise ValueError("max_saturated_fraction must be between 0 and 1")
        if not 0 <= self.edge_margin_ratio < 0.5:
            raise ValueError("edge_margin_ratio must be between 0 and 0.5")


@dataclass(frozen=True, slots=True)
class CropQuality:
    """Measured crop quality with user-facing reasons for rejection."""

    focus_score: float
    mean_luma: float
    saturated_fraction: float
    target_width: float
    target_height: float
    edge_clipped: bool
    ready: bool
    reasons: tuple[str, ...]

    @property
    def hint(self) -> str:
        if "target too small" in self.reasons:
            return "Move closer"
        if "target touches frame edge" in self.reasons:
            return "Keep the target inside the frame"
        if "too dark" in self.reasons or "too bright" in self.reasons:
            return "Improve light"
        if "overexposed" in self.reasons:
            return "Reduce glare"
        if "blurry" in self.reasons:
            return "Hold steady and improve focus"
        return "Ready"


def evaluate_crop(
    crop: np.ndarray,
    source_box: BoundingBox,
    source_width: int,
    source_height: int,
    config: QualityConfig | None = None,
) -> CropQuality:
    """Evaluate the candidate crop, never the full camera frame."""

    quality_config = config or QualityConfig()
    if not isinstance(crop, np.ndarray) or crop.ndim != 3 or crop.shape[2] != 3:
        raise ValueError(f"expected a 3-channel BGR crop, got {getattr(crop, 'shape', None)!r}")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    focus_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean_luma = float(gray.mean())
    saturated_fraction = float(
        np.logical_or(gray <= 3, gray >= 252).sum() / max(gray.size, 1)
    )
    target_width = source_box.width
    target_height = source_box.height
    edge_margin_x = source_width * quality_config.edge_margin_ratio
    edge_margin_y = source_height * quality_config.edge_margin_ratio
    edge_clipped = (
        source_box.x1 <= edge_margin_x
        or source_box.y1 <= edge_margin_y
        or source_box.x2 >= source_width - edge_margin_x
        or source_box.y2 >= source_height - edge_margin_y
    )

    reasons: list[str] = []
    if target_width < quality_config.min_target_width or target_height < quality_config.min_target_height:
        reasons.append("target too small")
    if edge_clipped:
        reasons.append("target touches frame edge")
    if mean_luma < quality_config.min_mean_luma:
        reasons.append("too dark")
    if mean_luma > quality_config.max_mean_luma:
        reasons.append("too bright")
    if saturated_fraction > quality_config.max_saturated_fraction:
        reasons.append("overexposed")
    if focus_score < quality_config.min_laplacian_variance:
        reasons.append("blurry")

    return CropQuality(
        focus_score=focus_score,
        mean_luma=mean_luma,
        saturated_fraction=saturated_fraction,
        target_width=target_width,
        target_height=target_height,
        edge_clipped=edge_clipped,
        ready=not reasons,
        reasons=tuple(reasons),
    )
