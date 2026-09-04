"""Independent weed-beta inference boundary.

The beta has its own manifest and ONNX detector.  It never reuses the plant
classifier, never writes image files, and reports missing/invalid model assets
as an explicit unavailable state.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Callable

import cv2
import numpy as np

from botanika.core.settings import AppSettings
from botanika.storage.weeds import NO_POSITION_MESSAGE, WeedObservationStore
from botanika.vision.detection import BoundingBox, Detection, DetectorError, ModelManifest, YoloOnnxDetector


class WeedUnavailable(RuntimeError):
    """Raised when the optional weed beta cannot run."""


@dataclass(frozen=True, slots=True)
class WeedDetectorManifest:
    manifest_path: Path
    model_name: str
    version: str
    region: str
    crop_context: str
    source: str
    license: str
    labels: tuple[str, ...]
    artifact_path: Path
    artifact_sha256: str
    input_width: int
    input_height: int
    model_manifest: ModelManifest
    source_model_card: str | None = None
    source_revision: str | None = None
    license_url: str | None = None
    inference_notes: str | None = None
    limitations: str | None = None
    artifact_export_license_metadata: str | None = None
    reported_metrics: dict[str, Any] | None = None

    @classmethod
    def from_file(cls, path: Path) -> "WeedDetectorManifest":
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise WeedUnavailable(f"weed beta manifest is unavailable: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise WeedUnavailable(f"could not read weed beta manifest: {exc}") from exc
        required = ("model_name", "version", "region", "crop_context", "source", "license", "labels", "artifact", "sha256")
        missing = [key for key in required if key not in value]
        if missing:
            raise WeedUnavailable(f"weed beta manifest is missing: {', '.join(missing)}")
        labels = tuple(str(item).strip() for item in value["labels"])
        if not labels or any(not item for item in labels):
            raise WeedUnavailable("weed beta manifest must define supported labels")
        input_size = value.get("input_size", [640, 640])
        if not isinstance(input_size, list) or len(input_size) != 2:
            raise WeedUnavailable("weed beta manifest input_size is invalid")
        manifest_path = Path(path).resolve()
        artifact_path = (manifest_path.parent / str(value["artifact"])).resolve()
        # YoloOnnxDetector consumes the same output contract.  Keep its
        # ephemeral manifest in memory rather than writing a runtime file.
        model_manifest = ModelManifest(
            manifest_path=manifest_path,
            artifact_path=artifact_path,
            model_name=str(value["model_name"]),
            version=str(value["version"]),
            source=str(value["source"]),
            license=str(value["license"]),
            labels=labels,
            sha256=str(value["sha256"]).lower(),
            input_width=int(input_size[0]),
            input_height=int(input_size[1]),
            has_objectness=bool(value.get("has_objectness", False)),
            output_layout=str(value.get("output_layout", "features_first")),
        )
        return cls(
            manifest_path=manifest_path,
            model_name=str(value["model_name"]),
            version=str(value["version"]),
            region=str(value["region"]),
            crop_context=str(value["crop_context"]),
            source=str(value["source"]),
            license=str(value["license"]),
            labels=labels,
            artifact_path=artifact_path,
            artifact_sha256=str(value["sha256"]).lower(),
            input_width=int(input_size[0]),
            input_height=int(input_size[1]),
            model_manifest=model_manifest,
            source_model_card=_optional_text(value.get("source_model_card")),
            source_revision=_optional_text(value.get("source_revision")),
            license_url=_optional_text(value.get("license_url")),
            inference_notes=_optional_text(value.get("inference_notes")),
            limitations=_optional_text(value.get("limitations")),
            artifact_export_license_metadata=_optional_text(value.get("artifact_export_license_metadata")),
            reported_metrics=(
                dict(value["reported_metrics"])
                if isinstance(value.get("reported_metrics"), dict)
                else None
            ),
        )

    def digest(self) -> str:
        return hashlib.sha256(self.manifest_path.read_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class WeedDetection:
    weed_class: str
    confidence: float
    box: BoundingBox

    def to_dict(self) -> dict[str, Any]:
        return {
            "weed_class": self.weed_class,
            "confidence": self.confidence,
            "box": {
                "x1": self.box.x1,
                "y1": self.box.y1,
                "x2": self.box.x2,
                "y2": self.box.y2,
            },
        }


@dataclass(frozen=True, slots=True)
class WeedServiceStatus:
    available: bool
    state: str
    detail: str
    manifest: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "state": self.state,
            "detail": self.detail,
            "manifest": self.manifest,
            "image_persistence": "disabled",
        }


class WeedService:
    """Load one independent detector and process one still image at a time."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        detector: Any | None = None,
        observation_store: WeedObservationStore | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings
        self._clock = clock
        self.observation_store = observation_store
        self.manifest: WeedDetectorManifest | None = None
        self.detector = detector
        self.error: str | None = None
        try:
            self.manifest = WeedDetectorManifest.from_file(settings.weed_manifest_path)
            if self.detector is None:
                self.detector = YoloOnnxDetector(
                    self.manifest.model_manifest,
                    confidence_threshold=settings.weed_confidence,
                    nms_iou_threshold=settings.weed_nms_iou,
                )
                self.detector.load()
        except (WeedUnavailable, DetectorError, OSError, ValueError) as exc:
            self.error = str(exc)
            self.detector = None

    @property
    def detector_version(self) -> str:
        return self.manifest.version if self.manifest is not None else "unavailable"

    def status(self) -> WeedServiceStatus:
        manifest = None
        if self.manifest is not None:
            manifest = {
                "model_name": self.manifest.model_name,
                "version": self.manifest.version,
                "region": self.manifest.region,
                "crop_context": self.manifest.crop_context,
                "source": self.manifest.source,
                "license": self.manifest.license,
                "license_url": self.manifest.license_url,
                "source_model_card": self.manifest.source_model_card,
                "source_revision": self.manifest.source_revision,
                "inference_notes": self.manifest.inference_notes,
                "limitations": self.manifest.limitations,
                "artifact_export_license_metadata": self.manifest.artifact_export_license_metadata,
                "reported_metrics": self.manifest.reported_metrics,
                "labels": list(self.manifest.labels),
                "artifact_path": str(self.manifest.artifact_path),
                "artifact_sha256": self.manifest.artifact_sha256,
                "manifest_sha256": self.manifest.digest() if self.manifest.manifest_path.is_file() else None,
            }
        return WeedServiceStatus(
            available=self.detector is not None,
            state="ready" if self.detector is not None else "unavailable",
            detail="Independent weed detector is loaded." if self.detector is not None else (self.error or "weed detector is unavailable"),
            manifest=manifest,
        )

    def detect_bytes(
        self,
        payload: bytes,
        *,
        position: dict[str, Any] | None = None,
        include_frame: bool = False,
    ) -> dict[str, Any]:
        if not payload:
            raise ValueError("weed image is empty")
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("weed image could not be decoded")
        return self.detect_image(image, position=position, include_frame=include_frame)

    def detect_image(
        self,
        image: np.ndarray,
        *,
        position: dict[str, Any] | None = None,
        include_frame: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
            raise ValueError("weed input must be a uint8 three-channel image")
        status = self.status()
        if self.detector is None or self.manifest is None:
            return {
                "status": "unavailable",
                "detail": status.detail,
                "detections": [],
                "detector_version": self.detector_version,
                "crop_context": self.manifest.crop_context if self.manifest else "unavailable",
                "position_message": NO_POSITION_MESSAGE,
                "position_available": False,
                "run_id": None,
                "image_persisted": False,
                "image_width": int(image.shape[1]),
                "image_height": int(image.shape[0]),
            }
        try:
            generic = self.detector.detect(image)
        except DetectorError as exc:
            self.error = str(exc)
            return {
                "status": "unavailable",
                "detail": f"weed inference failed: {exc}",
                "detections": [],
                "detector_version": self.detector_version,
                "crop_context": self.manifest.crop_context,
                "position_message": NO_POSITION_MESSAGE,
                "position_available": False,
                "run_id": None,
                "image_persisted": False,
                "image_width": int(image.shape[1]),
                "image_height": int(image.shape[0]),
            }
        detections = tuple(
            WeedDetection(item.label, float(item.confidence), item.box)
            for item in generic
            if item.label in self.manifest.labels
        )
        normalized_position = _position_if_accurate(position, self.settings.weed_position_max_accuracy_m)
        position_message = "Coordinate recorded with the weed observation." if normalized_position else NO_POSITION_MESSAGE
        run = None
        # Weed runs are meaningful only when at least one supported box has a
        # validated coordinate. A denied/malformed/inaccurate position must
        # not leave a run row behind, even though inference still succeeds.
        if self.observation_store is not None and normalized_position is not None and detections:
            run = self.observation_store.save_run(
                detections,
                detector_version=self.manifest.version,
                crop_context=self.manifest.crop_context,
                model_metadata={
                    "model_name": self.manifest.model_name,
                    "version": self.manifest.version,
                    "manifest_sha256": self.manifest.digest(),
                    "source": self.manifest.source,
                    "license": self.manifest.license,
                    "license_url": self.manifest.license_url,
                    "source_revision": self.manifest.source_revision,
                },
                position=normalized_position,
                observed_at=self._clock(),
            )
        result = {
            "status": "ready",
            "detail": "Weed beta frame analyzed; temporary image was discarded.",
            "detections": [item.to_dict() for item in detections],
            "detector_version": self.manifest.version,
            "crop_context": self.manifest.crop_context,
            "position_message": position_message,
            "position_available": normalized_position is not None,
            "run_id": run.run_id if run is not None else None,
            "image_persisted": False,
            "image_width": int(image.shape[1]),
            "image_height": int(image.shape[0]),
        }
        if include_frame:
            result["frame_data_url"] = _jpeg_data_url(image)
        return result


def _position_if_accurate(position: dict[str, Any] | None, maximum_accuracy: float) -> dict[str, Any] | None:
    if position is None:
        return None
    try:
        value = dict(position)
        latitude = float(value["latitude"])
        longitude = float(value["longitude"])
        accuracy = float(value["accuracy_m"])
        source = str(value.get("source", "")).strip()
        timestamp_value = value.get("timestamp", time.time())
        timestamp = float(time.time() if timestamp_value is None else timestamp_value)
    except (TypeError, ValueError, KeyError):
        return None
    if (
        not np.isfinite(latitude)
        or not -90 <= latitude <= 90
        or not np.isfinite(longitude)
        or not -180 <= longitude <= 180
        or not np.isfinite(accuracy)
        or accuracy < 0
        or accuracy > maximum_accuracy
        or not source
        or not np.isfinite(timestamp)
        or timestamp < 0
    ):
        return None
    return {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy_m": accuracy,
        "source": source,
        "timestamp": timestamp,
    }


def _optional_text(value: Any) -> str | None:
    """Normalize optional manifest metadata without admitting blank strings."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _jpeg_data_url(image: np.ndarray) -> str:
    """Encode the analyzed frame in memory for the SOLO response only."""

    encoded_ok, encoded = cv2.imencode(
        ".jpg",
        image,
        [int(cv2.IMWRITE_JPEG_QUALITY), 82],
    )
    if not encoded_ok:
        raise ValueError("weed frame could not be encoded")
    payload = base64.b64encode(encoded.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


__all__ = [
    "WeedDetection",
    "WeedDetectorManifest",
    "WeedService",
    "WeedServiceStatus",
    "WeedUnavailable",
]
