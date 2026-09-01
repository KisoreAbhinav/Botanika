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
    minimum_appearance_similarity: float = 0.70
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
        if not 0 <= self.minimum_appearance_similarity <= 1:
            raise ValueError("minimum_appearance_similarity must be between 0 and 1")
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
        self._appearance: np.ndarray | None = None
        self._captured_target: Detection | None = None
        self._captured_appearance: np.ndarray | None = None
        self._rearm_missing_frames = 0

    @property
    def current_detection(self) -> Detection | None:
        return self._current

    @property
    def last_capture(self) -> CaptureResult | None:
        return self._last_capture

    def update(self, frame: np.ndarray, detections: Iterable[Detection]) -> LockOnUpdate:
        """Advance one frame and capture automatically after a quality lock."""

        frame_height, frame_width = frame.shape[:2]
        candidate = select_candidate(
            detections,
            frame_width,
            frame_height,
            self.config.eligible_labels,
        )
        candidate_appearance = (
            _appearance_signature(frame, candidate.box) if candidate is not None else None
        )

        if self.state == LockOnState.CAPTURED:
            self.state = LockOnState.COOLDOWN
            self._cooldown_remaining = self.config.cooldown_frames
        if self.state == LockOnState.COOLDOWN:
            if self._cooldown_remaining > 0:
                self._cooldown_remaining -= 1
                return self._result("Cooldown")
            if self._captured_target is not None:
                if candidate is None:
                    self._rearm_missing_frames += 1
                    self._current = None
                    if self._rearm_missing_frames <= self.config.disappearance_tolerance:
                        return self._result("Clear the previous target to rearm")
                    self._reset_tracking(clear_capture_guard=True)
                    return self._result("Ready for a new target")
                self._rearm_missing_frames = 0
                if self._matches(
                    self._captured_target,
                    candidate,
                    frame_width,
                    frame_height,
                    self._captured_appearance,
                    candidate_appearance,
                ):
                    self._current = candidate
                    self._appearance = candidate_appearance
                    return self._result("Move to another target or clear the frame")
                self._reset_tracking(clear_capture_guard=True)
            else:
                self._reset_tracking()

        if self.state in (
            LockOnState.CHECKING_SHARPNESS,
            LockOnState.LOCKED,
            LockOnState.CAPTURING,
        ):
            active_state = self.state
            if (
                candidate is not None
                and self._current is not None
                and self._matches(
                    self._current,
                    candidate,
                    frame_width,
                    frame_height,
                    self._appearance,
                    candidate_appearance,
                )
            ):
                self._current = candidate
                self._appearance = _blend_appearance(
                    self._appearance, candidate_appearance
                )
                crop = _extract_crop(frame, candidate.box)
                self._quality = evaluate_crop(
                    crop,
                    candidate.box,
                    frame_width,
                    frame_height,
                    self.config.quality,
                )
                if not self._quality.ready:
                    self.state = LockOnState.CHECKING_SHARPNESS
                    return self._result(self._quality.hint)
                if active_state == LockOnState.CHECKING_SHARPNESS:
                    self.state = LockOnState.LOCKED
                    hint = (
                        "Target locked"
                        if self.config.automatic_capture
                        else "Locked — press Space to capture"
                    )
                    return self._result(hint)
                if active_state == LockOnState.LOCKED:
                    if not self.config.automatic_capture:
                        return self._result("Locked — press Space to capture")
                    self.state = LockOnState.CAPTURING
                    return self._result("Capturing crop")
                return self._capture(frame, candidate)
            self._reset_tracking()

        if candidate is None:
            if self._current is not None and self._missing_frames < self.config.disappearance_tolerance:
                self._missing_frames += 1
                self.state = LockOnState.TRACKING
                return self._result("Target briefly disappeared")
            self._reset_tracking()
            return self._result("Searching for an eligible target")

        self._missing_frames = 0
        if self._current is None or not self._matches(
            self._current,
            candidate,
            frame_width,
            frame_height,
            self._appearance,
            candidate_appearance,
        ):
            self._current = candidate
            self._appearance = candidate_appearance
            self._stable_checks = 1
            self._quality = None
            self.state = LockOnState.TRACKING
            return self._result("Target found — hold steady")

        self._current = candidate
        self._appearance = _blend_appearance(self._appearance, candidate_appearance)
        self._stable_checks += 1
        if self._stable_checks < self.config.stable_checks:
            self.state = LockOnState.HOLD_STEADY
            return self._result("Hold steady")

        self.state = LockOnState.CHECKING_SHARPNESS
        self._quality = None
        return self._result("Checking sharpness")

    def manual_capture(self, frame: np.ndarray) -> LockOnUpdate:
        """Capture the current candidate for debugging, even before auto-lock."""

        if self._current is None:
            return self._result("No eligible target to capture")
        self.state = LockOnState.CAPTURING
        capture = self.crop_store.save(frame, self._current.box, manual=True)
        self._last_capture = capture
        self._captured_target = self._current
        self._captured_appearance = self._appearance
        self._rearm_missing_frames = 0
        self.state = LockOnState.CAPTURED
        return self._result("Manual crop captured", capture=capture)

    def _capture(self, frame: np.ndarray, candidate: Detection) -> LockOnUpdate:
        capture = self.crop_store.save(frame, candidate.box)
        self._last_capture = capture
        self._captured_target = candidate
        self._captured_appearance = self._appearance
        self._rearm_missing_frames = 0
        self.state = LockOnState.CAPTURED
        hint = "Crop captured" if capture.path else "Duplicate crop skipped"
        return self._result(hint, capture=capture)

    def _matches(
        self,
        previous: Detection,
        current: Detection,
        frame_width: int,
        frame_height: int,
        previous_appearance: np.ndarray | None,
        current_appearance: np.ndarray | None,
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
        if max(width_change, height_change) > self.config.maximum_relative_size_change:
            return False
        return (
            _appearance_similarity(previous_appearance, current_appearance)
            >= self.config.minimum_appearance_similarity
        )

    def _reset_tracking(self, *, clear_capture_guard: bool = False) -> None:
        self.state = LockOnState.SEARCHING
        self._current = None
        self._stable_checks = 0
        self._missing_frames = 0
        self._quality = None
        self._appearance = None
        self._last_capture = None
        self._cooldown_remaining = 0
        self._rearm_missing_frames = 0
        if clear_capture_guard:
            self._captured_target = None
            self._captured_appearance = None

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


def _appearance_signature(frame: np.ndarray, box: BoundingBox) -> np.ndarray:
    """Return a compact normalized BGR histogram for target matching."""

    crop = _extract_crop(frame, box)
    histograms = [
        np.histogram(crop[:, :, channel], bins=16, range=(0, 256))[0].astype(np.float64)
        for channel in range(3)
    ]
    signature = np.concatenate(histograms)
    norm = float(np.linalg.norm(signature))
    return signature / norm if norm > 0 else signature


def _appearance_similarity(
    previous: np.ndarray | None, current: np.ndarray | None
) -> float:
    if previous is None or current is None:
        return 1.0
    return float(np.clip(np.dot(previous, current), 0.0, 1.0))


def _blend_appearance(
    previous: np.ndarray | None, current: np.ndarray | None
) -> np.ndarray | None:
    if previous is None:
        return current
    if current is None:
        return previous
    blended = previous * 0.8 + current * 0.2
    norm = float(np.linalg.norm(blended))
    return blended / norm if norm > 0 else blended


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
