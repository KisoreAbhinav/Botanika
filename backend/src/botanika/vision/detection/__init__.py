"""Generic object-detection contracts and implementations."""

from .geometry import (
    BoundingBox,
    DisplayTransform,
    LetterboxTransform,
    fit_frame_to_window,
)
from .yolo import (
    Detection,
    DetectorError,
    DetectorInferenceError,
    DetectorLoadError,
    DetectorMetrics,
    DetectorUnavailable,
    ModelManifest,
    YoloOnnxDetector,
)

__all__ = [
    "BoundingBox",
    "Detection",
    "DisplayTransform",
    "LetterboxTransform",
    "DetectorError",
    "DetectorInferenceError",
    "DetectorLoadError",
    "DetectorMetrics",
    "DetectorUnavailable",
    "Detection",
    "ModelManifest",
    "YoloOnnxDetector",
    "fit_frame_to_window",
]

