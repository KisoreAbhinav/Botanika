"""Serializable scan state snapshots published to the kiosk event channel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from botanika.vision.classification import ClassificationRun
from botanika.vision.detection import Detection
from botanika.vision.quality import CaptureResult, CropQuality, LockOnState, LockOnUpdate
from botanika.vision.services.overlay import OverlayTransform


@dataclass(frozen=True, slots=True)
class ScanSnapshot:
    """One atomic view of the Scan service for the browser.

    Every event carries the source/preview dimensions, frame timing, and box
    coordinates so the overlay transformation is reproducible in tests and in
    the kiosk.
    """

    sequence: int
    timestamp: float
    session_id: str
    mode: str
    state: LockOnState
    hint: str
    transform: OverlayTransform | None
    source_sequence: int | None
    source_timestamp: float | None
    detections: tuple[Detection, ...] = ()
    selected_index: int | None = None
    quality: CropQuality | None = None
    stable_checks: int = 0
    required_checks: int = 0
    capture: CaptureResult | None = None
    classification: ClassificationRun | None = None
    processing: bool = False
    camera_available: bool = True
    detector_p50_ms: float = 0.0
    detector_p95_ms: float = 0.0
    error: str | None = None

    @property
    def selected(self) -> Detection | None:
        if self.selected_index is None or self.selected_index >= len(self.detections):
            return None
        return self.detections[self.selected_index]

    def to_dict(self) -> dict[str, Any]:
        frame: dict[str, object] | None = None
        if self.transform is not None:
            frame = {
                "source_width": self.transform.source_width,
                "source_height": self.transform.source_height,
                "preview_width": self.transform.preview_width,
                "preview_height": self.transform.preview_height,
                "scale": self.transform.scale,
                "offset_x": self.transform.offset_x,
                "offset_y": self.transform.offset_y,
                "rendered_width": self.transform.rendered_width,
                "rendered_height": self.transform.rendered_height,
                "source_sequence": self.source_sequence,
                "source_timestamp": self.source_timestamp,
            }
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "mode": self.mode,
            "state": self.state.value,
            "hint": self.hint,
            "frame": frame,
            "detections": [
                {
                    "class_id": detection.class_id,
                    "label": detection.label,
                    "confidence": detection.confidence,
                    "box": {
                        "x1": detection.box.x1,
                        "y1": detection.box.y1,
                        "x2": detection.box.x2,
                        "y2": detection.box.y2,
                    },
                }
                for detection in self.detections
            ],
            "selected_index": self.selected_index,
            "quality": None if self.quality is None else _quality_dict(self.quality),
            "stable_checks": self.stable_checks,
            "required_checks": self.required_checks,
            "capture": None if self.capture is None else _capture_dict(self.capture),
            "classification": None if self.classification is None else self.classification.to_dict(),
            "processing": self.processing,
            "camera_available": self.camera_available,
            "detector_latency": {
                "p50_ms": self.detector_p50_ms,
                "p95_ms": self.detector_p95_ms,
            },
            "error": self.error,
        }


def _quality_dict(quality: CropQuality) -> dict[str, object]:
    return {
        "focus_score": quality.focus_score,
        "mean_luma": quality.mean_luma,
        "saturated_fraction": quality.saturated_fraction,
        "target_width": quality.target_width,
        "target_height": quality.target_height,
        "edge_clipped": quality.edge_clipped,
        "ready": quality.ready,
        "reasons": list(quality.reasons),
        "hint": quality.hint,
    }


def _capture_dict(capture: CaptureResult) -> dict[str, object]:
    return {
        "path": str(capture.path) if capture.path is not None else None,
        "crop_box": {
            "x1": capture.crop_box.x1,
            "y1": capture.crop_box.y1,
            "x2": capture.crop_box.x2,
            "y2": capture.crop_box.y2,
        },
        "width": capture.width,
        "height": capture.height,
        "content_hash": capture.content_hash,
        "duplicate": capture.duplicate,
        "manual": capture.manual,
    }


def snapshot_from_update(
    sequence: int,
    timestamp: float,
    session_id: str,
    mode: str,
    transform: OverlayTransform | None,
    source_sequence: int | None,
    source_timestamp: float | None,
    detections: tuple[Detection, ...],
    selected_index: int | None,
    update: LockOnUpdate,
    processing: bool,
    camera_available: bool,
    detector_p50_ms: float,
    detector_p95_ms: float,
    classification: ClassificationRun | None = None,
    error: str | None = None,
) -> ScanSnapshot:
    """Build a snapshot from one lock-on engine update plus service context."""

    return ScanSnapshot(
        sequence=sequence,
        timestamp=timestamp,
        session_id=session_id,
        mode=mode,
        state=update.state,
        hint=update.hint,
        transform=transform,
        source_sequence=source_sequence,
        source_timestamp=source_timestamp,
        detections=detections,
        selected_index=selected_index,
        quality=update.quality,
        stable_checks=update.stable_checks,
        required_checks=update.required_checks,
        capture=update.capture,
        classification=classification,
        processing=processing,
        camera_available=camera_available,
        detector_p50_ms=detector_p50_ms,
        detector_p95_ms=detector_p95_ms,
        error=error,
    )