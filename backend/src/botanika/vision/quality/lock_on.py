"""Deterministic target tracking and automatic crop-capture state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Iterable

import numpy as np

from ..detection import BoundingBox, Detection
from .capture import CaptureResult, CropStore
from .quality import CropQuality, QualityConfig, evaluate_crop


class LockOnState(str, Enum):
    SEARCHING = "Searching"
    TRACKING = "Tracking"
    HOLD_STEADY = "Hold steady"
    CHECKING_SHARPNESS = "Checking sharpness"
    LOCKED = "Locked"
    CAPTURING = "Capturing"
    CAPTURED = "Captured"
    COOLDOWN = "Cooldown"


@dataclass(frozen=True, slots=True)
class LockOnConfig:
    """Tracking thresholds; quality values are calibration baselines."""

    eligible_labels: frozenset[str] = field(default_factory=lambda: frozenset({"potted plant"}))
    stable_checks: int = 4
    minimum_iou: float = 0.55
    maximum_center_displacement_ratio: float = 0.08
    maximum_relative_size_change: float = 0.20
    disappearance_tolerance: int = 2
    cooldown_frames: int = 30
    crop_padding_ratio: float = 0.08
    automatic_capture: bool = True
    quality: QualityConfig = field(default_factory=QualityConfig)

    def __post_init__(self) -> None:
        if self.stable_checks < 2:
            raise ValueError("stable_checks must be at least 2")
        if not 0 <= self.minimum_iou <= 1:
            raise ValueError("minimum_iou must be between 0 and 1")
        if self.maximum_center_displacement_ratio < 0 or self.maximum_relative_size_change < 0:
            raise ValueError("tracking limits must not be negative")
        if self.disappearance_tolerance < 0 or self.cooldown_frames < 0:
            raise ValueError("frame tolerances must not be negative")


@dataclass(frozen=True, slots=True)
class LockOnUpdate:
    state: LockOnState
    detection: Detection | None
    quality: CropQuality | None
    stable_checks: int
    required_checks: int
    hint: str
    capture: CaptureResult | None = None


def select_candidate(
    detections: Iterable[Detection],
    frame_width: int,
    frame_height: int,
    eligible_labels: frozenset[str],
) -> Detection | None:
    """Choose the largest eligible box, using centrality as the tie-breaker."""

    eligible = [detection for detection in detections if detection.label in eligible_labels]
    if not eligible:
        return None
    frame_center_x = frame_width / 2
    frame_center_y = frame_height / 2

    def rank(detection: Detection) -> tuple[float, float]:
        center_x = (detection.box.x1 + detection.box.x2) / 2
        center_y = (detection.box.y1 + detection.box.y2) / 2
        distance = math.hypot(
            (center_x - frame_center_x) / max(frame_width, 1),
            (center_y - frame_center_y) / max(frame_height, 1),
        )
        return (-detection.box.area, distance)

    return min(eligible, key=rank)


class LockOnEngine:
    """Track one eligible target and auto-save one crop when quality locks."""

    def __init__(self, config: LockOnConfig, crop_store: CropStore) -> None:
        self.config = config
        self.crop_store = crop_store
        self.state = LockOnState.SEARCHING
        self._current: Detection | None = None
        self._stable_checks = 0
        self._missing_frames = 0
        self._cooldown_remaining = 0
        self._quality: CropQuality | None = None
        self._last_capture: CaptureResult | None = None

    @property
    def current_detection(self) -> Detection | None:
        return self._current

    @property
    def last_capture(self) -> CaptureResult | None:
        return self._last_capture

    def update(self, frame: np.ndarray, detections: Iterable[Detection]) -> LockOnUpdate:
        """Advance one frame and capture automatically after a quality lock."""

        if self.state == LockOnState.CAPTURED:
            self.state = LockOnState.COOLDOWN
            self._cooldown_remaining = self.config.cooldown_frames
        if self.state == LockOnState.COOLDOWN:
            if self._cooldown_remaining > 0:
                self._cooldown_remaining -= 1
                return self._result("Cooldown", capture=self._last_capture)
            self._reset_tracking()

        frame_height, frame_width = frame.shape[:2]
        candidate = select_candidate(
            detections,
            frame_width,
            frame_height,
            self.config.eligible_labels,
        )
        if candidate is None:
            if self._current is not None and self._missing_frames < self.config.disappearance_tolerance:
                self._missing_frames += 1
                self.state = LockOnState.TRACKING
                return self._result("Target briefly disappeared")
            self._reset_tracking()
            return self._result("Searching for an eligible target")

        self._missing_frames = 0
        if self._current is None or not self._matches(self._current, candidate, frame_width, frame_height):
            self._current = candidate
            self._stable_checks = 1
            self._quality = None
            self.state = LockOnState.TRACKING
            return self._result("Target found — hold steady")

        self._current = candidate
        self._stable_checks += 1
        if self._stable_checks < self.config.stable_checks:
            self.state = LockOnState.HOLD_STEADY
            return self._result("Hold steady")

        self.state = LockOnState.CHECKING_SHARPNESS
        crop = _extract_crop(frame, candidate.box)
        self._quality = evaluate_crop(
            crop,
            candidate.box,
            frame_width,
            frame_height,
            self.config.quality,
        )
        if not self._quality.ready:
            return self._result(self._quality.hint)

        self.state = LockOnState.LOCKED
        if not self.config.automatic_capture:
            return self._result("Locked — press Space to capture")
        self.state = LockOnState.CAPTURING
        capture = self.crop_store.save(frame, candidate.box)
        self._last_capture = capture
        self.state = LockOnState.CAPTURED
        return self._result("Crop captured" if capture.path else "Duplicate crop skipped", capture=capture)

    def manual_capture(self, frame: np.ndarray) -> LockOnUpdate:
        """Capture the current candidate for debugging, even before auto-lock."""

        if self._current is None:
            return self._result("No eligible target to capture")
        self.state = LockOnState.CAPTURING
        capture = self.crop_store.save(frame, self._current.box, manual=True)
        self._last_capture = capture
        self.state = LockOnState.CAPTURED
        return self._result("Manual crop captured", capture=capture)

    def _matches(
        self,
        previous: Detection,
        current: Detection,
        frame_width: int,
        frame_height: int,
    ) -> bool:
        if previous.class_id != current.class_id or previous.label != current.label:
            return False
        if _iou(previous.box, current.box) < self.config.minimum_iou:
            return False
        previous_center = _center(previous.box)
        current_center = _center(current.box)
        center_displacement = math.hypot(
            (current_center[0] - previous_center[0]) / max(frame_width, 1),
            (current_center[1] - previous_center[1]) / max(frame_height, 1),
        )
        if center_displacement > self.config.maximum_center_displacement_ratio:
            return False
        width_change = abs(current.box.width - previous.box.width) / max(previous.box.width, 1e-9)
        height_change = abs(current.box.height - previous.box.height) / max(previous.box.height, 1e-9)
        return max(width_change, height_change) <= self.config.maximum_relative_size_change

    def _reset_tracking(self) -> None:
        self.state = LockOnState.SEARCHING
        self._current = None
        self._stable_checks = 0
        self._missing_frames = 0
        self._quality = None
        self._last_capture = None
        self._cooldown_remaining = 0

    def _result(self, hint: str, *, capture: CaptureResult | None = None) -> LockOnUpdate:
        return LockOnUpdate(
            state=self.state,
            detection=self._current,
            quality=self._quality,
            stable_checks=self._stable_checks,
            required_checks=self.config.stable_checks,
            hint=hint,
            capture=capture,
        )


def _extract_crop(frame: np.ndarray, box: BoundingBox) -> np.ndarray:
    height, width = frame.shape[:2]
    clamped = box.clamp(width, height)
    x1 = max(0, min(width - 1, math.floor(clamped.x1)))
    y1 = max(0, min(height - 1, math.floor(clamped.y1)))
    x2 = max(x1 + 1, min(width, math.ceil(clamped.x2)))
    y2 = max(y1 + 1, min(height, math.ceil(clamped.y2)))
    return np.ascontiguousarray(frame[y1:y2, x1:x2])


def _center(box: BoundingBox) -> tuple[float, float]:
    return ((box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2)


def _iou(left: BoundingBox, right: BoundingBox) -> float:
    intersection = BoundingBox(
        max(left.x1, right.x1),
        max(left.y1, right.y1),
        min(left.x2, right.x2),
        min(left.y2, right.y2),
    ).area
    union = left.area + right.area - intersection
    return intersection / union if union > 0 else 0.0
