"""Dedicated ONNX Runtime adapter for a generic pretrained YOLO detector."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Protocol

import cv2
import numpy as np

from .geometry import BoundingBox, LetterboxTransform


class DetectorError(RuntimeError):
    """Base error for model loading and inference."""


class DetectorUnavailable(DetectorError):
    """Raised when a model or its runtime is unavailable."""


class DetectorLoadError(DetectorError):
    """Raised when an artifact exists but cannot be loaded or validated."""


class DetectorInferenceError(DetectorError):
    """Raised when a loaded detector cannot process a frame."""


@dataclass(frozen=True, slots=True)
class ModelManifest:
    """Immutable model provenance and preprocessing/output contract."""

    manifest_path: Path
    artifact_path: Path
    model_name: str
    version: str
    source: str
    license: str
    labels: tuple[str, ...]
    sha256: str
    input_width: int = 640
    input_height: int = 640
    has_objectness: bool = False
    output_layout: str = "features_first"

    @classmethod
    def from_file(cls, path: Path) -> "ModelManifest":
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DetectorUnavailable(f"model manifest not found: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise DetectorLoadError(f"could not read model manifest {path}: {exc}") from exc

        required = ("artifact", "model_name", "version", "source", "license", "labels", "sha256")
        missing = [key for key in required if key not in values]
        if missing:
            raise DetectorLoadError(
                f"model manifest {path} is missing: {', '.join(missing)}"
            )
        artifact_path = (path.parent / values["artifact"]).resolve()
        labels = tuple(str(label) for label in values["labels"])
        if not labels or any(not label for label in labels):
            raise DetectorLoadError("model manifest labels must be non-empty")
        input_size = values.get("input_size", [640, 640])
        if len(input_size) != 2 or any(int(value) <= 0 for value in input_size):
            raise DetectorLoadError("model manifest input_size must contain two positive values")
        output_layout = str(values.get("output_layout", "features_first"))
        if output_layout not in {"features_first", "anchors_first"}:
            raise DetectorLoadError(
                "model manifest output_layout must be features_first or anchors_first"
            )
        return cls(
            manifest_path=path.resolve(),
            artifact_path=artifact_path,
            model_name=str(values["model_name"]),
            version=str(values["version"]),
            source=str(values["source"]),
            license=str(values["license"]),
            labels=labels,
            sha256=str(values["sha256"]).lower(),
            input_width=int(input_size[0]),
            input_height=int(input_size[1]),
            has_objectness=bool(values.get("has_objectness", False)),
            output_layout=output_layout,
        )

    def verify_artifact(self) -> None:
        if not self.artifact_path.is_file():
            raise DetectorUnavailable(
                f"detector artifact is unavailable: {self.artifact_path}"
            )
        digest = hashlib.sha256()
        try:
            with self.artifact_path.open("rb") as artifact:
                for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise DetectorLoadError(
                f"could not read detector artifact {self.artifact_path}: {exc}"
            ) from exc
        actual = digest.hexdigest()
        if actual != self.sha256:
            raise DetectorLoadError(
                f"detector checksum mismatch: expected {self.sha256}, got {actual}"
            )


@dataclass(frozen=True, slots=True)
class Detection:
    """One generic detector result; labels are never treated as species names."""

    class_id: int
    label: str
    confidence: float
    box: BoundingBox


@dataclass(slots=True)
class DetectorMetrics:
    """Bounded inference latency measurements for the live diagnostics."""

    max_samples: int = 300
    latencies_ms: list[float] = field(default_factory=list)

    def record(self, latency_ms: float) -> None:
        self.latencies_ms.append(float(latency_ms))
        if len(self.latencies_ms) > self.max_samples:
            del self.latencies_ms[: len(self.latencies_ms) - self.max_samples]

    def percentile(self, fraction: float) -> float:
        if not self.latencies_ms:
            return 0.0
        ordered = sorted(self.latencies_ms)
        index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
        return ordered[index]

    @property
    def p50_ms(self) -> float:
        return self.percentile(0.50)

    @property
    def p95_ms(self) -> float:
        return self.percentile(0.95)


class SessionInputLike(Protocol):
    name: str


class SessionOutputLike(Protocol):
    name: str


class InferenceSessionLike(Protocol):
    def get_inputs(self) -> list[SessionInputLike]: ...

    def get_outputs(self) -> list[SessionOutputLike]: ...

    def run(self, output_names: list[str], input_feed: dict[str, np.ndarray]) -> list[np.ndarray]: ...


def default_session_factory(path: Path) -> InferenceSessionLike:
    try:
        import onnxruntime as ort
    except Exception as exc:
        raise DetectorUnavailable(
            "ONNX Runtime is unavailable; install the Phase 0 Python requirements"
        ) from exc
    try:
        return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise DetectorLoadError(f"could not load ONNX detector {path}: {exc}") from exc


class YoloOnnxDetector:
    """Load once, infer on resized frames, and return source-frame boxes."""

    def __init__(
        self,
        manifest: ModelManifest,
        *,
        confidence_threshold: float = 0.25,
        nms_iou_threshold: float = 0.45,
        max_detections: int = 100,
        session_factory: Callable[[Path], InferenceSessionLike] = default_session_factory,
        metrics: DetectorMetrics | None = None,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be between 0 and 1")
        if not 0.0 <= nms_iou_threshold <= 1.0:
            raise ValueError("nms_iou_threshold must be between 0 and 1")
        if max_detections <= 0:
            raise ValueError("max_detections must be positive")
        self.manifest = manifest
        self.confidence_threshold = confidence_threshold
        self.nms_iou_threshold = nms_iou_threshold
        self.max_detections = max_detections
        self._session_factory = session_factory
        self._session: InferenceSessionLike | None = None
        self._input_name: str | None = None
        self._output_name: str | None = None
        self.metrics = metrics or DetectorMetrics()

    @property
    def is_loaded(self) -> bool:
        return self._session is not None

    def load(self) -> None:
        """Verify provenance and load the ONNX session outside the frame loop."""

        if self._session is not None:
            return
        self.manifest.verify_artifact()
        try:
            session = self._session_factory(self.manifest.artifact_path)
        except DetectorError:
            raise
        except Exception as exc:
            raise DetectorLoadError(f"could not create ONNX detector session: {exc}") from exc
        try:
            inputs = session.get_inputs()
            outputs = session.get_outputs()
        except Exception as exc:
            raise DetectorLoadError(f"could not inspect detector contract: {exc}") from exc
        if len(inputs) != 1 or not inputs[0].name:
            raise DetectorLoadError("YOLO detector must expose exactly one named input")
        if not outputs or not outputs[0].name:
            raise DetectorLoadError("YOLO detector must expose one named output")
        self._session = session
        self._input_name = inputs[0].name
        self._output_name = outputs[0].name

    def close(self) -> None:
        """Release the session reference; ONNX Runtime owns native cleanup."""

        self._session = None
        self._input_name = None
        self._output_name = None

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self._session is None or self._input_name is None or self._output_name is None:
            raise DetectorLoadError("detector is not loaded")
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise DetectorInferenceError(
                f"detector expected a 3-channel BGR frame, got {getattr(frame, 'shape', None)!r}"
            )

        source_height, source_width = frame.shape[:2]
        transform = LetterboxTransform.for_image(
            source_width,
            source_height,
            self.manifest.input_width,
            self.manifest.input_height,
        )
        resized = cv2.resize(
            frame,
            (transform.resized_width, transform.resized_height),
            interpolation=cv2.INTER_LINEAR,
        )
        letterboxed = np.full(
            (self.manifest.input_height, self.manifest.input_width, 3),
            114,
            dtype=np.uint8,
        )
        letterboxed[
            transform.pad_top : transform.pad_top + transform.resized_height,
            transform.pad_left : transform.pad_left + transform.resized_width,
        ] = resized
        rgb = cv2.cvtColor(letterboxed, cv2.COLOR_BGR2RGB)
        tensor = np.transpose(rgb.astype(np.float32) / 255.0, (2, 0, 1))[None, ...]

        started_at = time.perf_counter()
        try:
            outputs = self._session.run([self._output_name], {self._input_name: tensor})
        except Exception as exc:
            raise DetectorInferenceError(f"YOLO inference failed: {exc}") from exc
        self.metrics.record((time.perf_counter() - started_at) * 1000.0)
        try:
            return self._decode_output(np.asarray(outputs[0]), transform)
        except DetectorError:
            raise
        except Exception as exc:
            raise DetectorInferenceError(f"could not decode YOLO output: {exc}") from exc

    def _decode_output(
        self,
        output: np.ndarray,
        transform: LetterboxTransform,
    ) -> list[Detection]:
        if output.ndim == 3:
            output = output[0]
        if output.ndim != 2:
            raise DetectorInferenceError(f"unsupported YOLO output shape: {output.shape!r}")
        if self.manifest.output_layout == "features_first":
            output = output.T

        score_start = 5 if self.manifest.has_objectness else 4
        if output.shape[1] <= score_start:
            raise DetectorInferenceError(f"unsupported YOLO output shape: {output.shape!r}")
        class_count = min(output.shape[1] - score_start, len(self.manifest.labels))
        if class_count <= 0:
            raise DetectorInferenceError("YOLO output contains no known class scores")

        class_scores = output[:, score_start : score_start + class_count]
        if self.manifest.has_objectness:
            class_scores = class_scores * output[:, 4:5]
        class_ids = np.argmax(class_scores, axis=1)
        confidences = class_scores[np.arange(len(class_scores)), class_ids]
        valid = np.isfinite(confidences) & (confidences >= self.confidence_threshold)

        centers = output[:, :2]
        sizes = output[:, 2:4]
        xyxy = np.column_stack(
            (
                centers[:, 0] - sizes[:, 0] / 2,
                centers[:, 1] - sizes[:, 1] / 2,
                centers[:, 0] + sizes[:, 0] / 2,
                centers[:, 1] + sizes[:, 1] / 2,
            )
        )
        candidates: list[Detection] = []
        for index in np.flatnonzero(valid):
            box = transform.to_source_box(
                BoundingBox(*[float(value) for value in xyxy[index]])
            )
            if box.area <= 0:
                continue
            class_id = int(class_ids[index])
            candidates.append(
                Detection(
                    class_id=class_id,
                    label=self.manifest.labels[class_id],
                    confidence=float(confidences[index]),
                    box=box,
                )
            )
        return _class_aware_nms(candidates, self.nms_iou_threshold, self.max_detections)


def _intersection_over_union(left: BoundingBox, right: BoundingBox) -> float:
    intersection = BoundingBox(
        max(left.x1, right.x1),
        max(left.y1, right.y1),
        min(left.x2, right.x2),
        min(left.y2, right.y2),
    ).area
    union = left.area + right.area - intersection
    return intersection / union if union > 0 else 0.0


def _class_aware_nms(
    detections: list[Detection], iou_threshold: float, max_detections: int
) -> list[Detection]:
    kept: list[Detection] = []
    for class_id in sorted({detection.class_id for detection in detections}):
        pending = sorted(
            (detection for detection in detections if detection.class_id == class_id),
            key=lambda detection: detection.confidence,
            reverse=True,
        )
        while pending:
            current = pending.pop(0)
            kept.append(current)
            pending = [
                detection
                for detection in pending
                if _intersection_over_union(current.box, detection.box) < iou_threshold
            ]
    return sorted(kept, key=lambda detection: detection.confidence, reverse=True)[:max_detections]
