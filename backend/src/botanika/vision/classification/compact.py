"""Compact catalog classifier used by the Phase 6 standalone runtime.

This is a deliberately small, dependency-light baseline: a calibrated
nearest-centroid model over colour, texture, and crop-shape features.  It is a
real inference artifact and is never labelled as demo data, but it is not
silently presented as a field-trained neural model.  The artifact checksum,
immutable label map, provenance, and abstention gate are verified at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import cv2
import numpy as np

from botanika.knowledge.catalog import CatalogDefinition, CatalogIntegrityError, SpeciesRecord, load_catalog

from .classifier import (
    ClassificationResult,
    ClassificationStatus,
    ClassifierError,
    ClassifierInput,
    CancellationToken,
    MalformedImageError,
    SpeciesClassifier,
    SpeciesSuggestion,
    _cancelled,
    _load_crop,
)


FEATURE_SCHEMA = "hsv-luma-texture-v1"
FEATURE_NAMES = (
    "hue_mean",
    "saturation_mean",
    "value_mean",
    "hue_std",
    "saturation_std",
    "value_std",
    "green_fraction",
    "yellow_fraction",
    "brown_fraction",
    "red_fraction",
    "edge_density",
    "texture_score",
    "aspect_ratio",
    "center_green_fraction",
)


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    """Validated runtime metadata exposed to diagnostics and capabilities."""

    model_id: str
    version: str
    runtime: str
    artifact_path: Path
    artifact_sha256: str
    preprocessing: Mapping[str, Any]
    metrics: Mapping[str, Any]
    calibration: Mapping[str, Any]
    provenance: Mapping[str, Any]
    deployment_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "runtime": self.runtime,
            "artifact_path": str(self.artifact_path),
            "artifact_sha256": self.artifact_sha256,
            "preprocessing": dict(self.preprocessing),
            "metrics": dict(self.metrics),
            "calibration": dict(self.calibration),
            "provenance": dict(self.provenance),
            "deployment_ready": self.deployment_ready,
        }


class CompactSpeciesClassifier(SpeciesClassifier):
    """Checksum-verified, catalog-joined, CPU-friendly species classifier."""

    is_stub = False

    def __init__(
        self,
        model_path: Path,
        catalog_path: Path,
        *,
        acceptance_threshold: float | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        self.catalog: CatalogDefinition = load_catalog(Path(catalog_path))
        self._raw_model = _read_model(self.model_path)
        self._metadata = _validate_model(self._raw_model, self.model_path, self.catalog)
        self.classifier_version = self._metadata.version
        raw_labels = self._raw_model["label_map"]
        self.label_map = MappingProxyType({int(key): str(value) for key, value in raw_labels.items()})
        self._species_by_id = self.catalog.species_by_id()
        self._centroids = np.asarray(self._raw_model["centroids"], dtype=np.float32)
        self._scales = np.asarray(self._raw_model["feature_scales"], dtype=np.float32)
        calibration = self._metadata.calibration
        self.acceptance_threshold = float(
            acceptance_threshold
            if acceptance_threshold is not None
            else calibration.get("acceptance_threshold", 0.62)
        )
        self.minimum_margin = float(calibration.get("minimum_margin", 0.08))
        self.unknown_distance = float(calibration.get("unknown_distance", 0.42))
        self.temperature = max(0.001, float(calibration.get("temperature", 0.08)))
        self.suggestion_limit = max(1, int(calibration.get("suggestion_limit", 3)))
        self.deployment_ready = self._metadata.deployment_ready
        self.deployment_blocker = (
            None
            if self.deployment_ready
            else "Held-out metrics, unknown-rejection trials, and Pi benchmark evidence are incomplete."
        )
        if not 0.0 <= self.acceptance_threshold <= 1.0:
            raise ClassifierError("classifier acceptance threshold must be between 0 and 1")
        if self._centroids.shape != (len(self.label_map), len(FEATURE_NAMES)):
            raise ClassifierError("classifier centroid dimensions do not match feature schema")
        if self._scales.shape != (len(FEATURE_NAMES),) or np.any(self._scales <= 0):
            raise ClassifierError("classifier feature scales must be positive")

    @property
    def metadata(self) -> ModelMetadata:
        return self._metadata

    @property
    def model_release(self) -> dict[str, Any]:
        return {
            "model_id": self._metadata.model_id,
            "version": self._metadata.version,
            "runtime": self._metadata.runtime,
            "artifact_sha256": self._metadata.artifact_sha256,
            "label_map": dict(self.label_map),
            "preprocessing": dict(self._metadata.preprocessing),
            "metrics": dict(self._metadata.metrics),
            "calibration": dict(self._metadata.calibration),
            "provenance": dict(self._metadata.provenance),
        }

    def classify(
        self,
        crop: ClassifierInput,
        *,
        cancellation: CancellationToken | None = None,
    ) -> ClassificationResult:
        if _cancelled(cancellation):
            return self._failure(ClassificationStatus.CANCELLED, "Classification cancelled before inference")
        try:
            image = _load_crop(crop)
        except MalformedImageError as exc:
            return self._failure(ClassificationStatus.MALFORMED_IMAGE, str(exc))
        if _cancelled(cancellation):
            return self._failure(ClassificationStatus.CANCELLED, "Classification cancelled before inference")
        try:
            features = extract_features(image)
            distances = np.sqrt(np.mean(((self._centroids - features) / self._scales) ** 2, axis=1))
            order = np.argsort(distances)
            best_index = int(order[0])
            second_index = int(order[1]) if len(order) > 1 else best_index
            best_distance = float(distances[best_index])
            second_distance = float(distances[second_index])
            probabilities = _distance_probabilities(distances, self.temperature)
            confidence = float(np.clip(1.0 - best_distance / max(self.unknown_distance, 1e-6), 0.0, 1.0))
            # A close second class is evidence that the view is ambiguous even
            # if the top class's raw distance is acceptable.
            margin = float(probabilities[best_index] - probabilities[second_index])
        except (ValueError, cv2.error, FloatingPointError) as exc:
            return self._failure(ClassificationStatus.ERROR, f"feature inference failed: {exc}")
        if _cancelled(cancellation):
            return self._failure(ClassificationStatus.CANCELLED, "Classification cancelled after inference")

        suggestions = tuple(
            SpeciesSuggestion(
                common_name=self._species_by_id[self.label_map[int(index)]].common_name,
                scientific_name=self._species_by_id[self.label_map[int(index)]].scientific_name,
                confidence=float(np.clip(probabilities[int(index)], 0.0, 1.0)),
            )
            for index in order[: self.suggestion_limit]
        )
        if (
            best_distance > self.unknown_distance
            or confidence < self.acceptance_threshold
            or margin < self.minimum_margin
        ):
            return ClassificationResult(
                status=ClassificationStatus.UNCERTAIN,
                confidence=confidence,
                short_notes=(
                    "This view is outside the confident catalog range. Try a clear leaf, flower, "
                    "fruit, bark, or whole-plant view."
                ),
                sources=("botanika:india-starter-catalog",),
                classifier_version=self.classifier_version,
                suggestions=suggestions,
            )

        if not self.deployment_ready:
            return ClassificationResult(
                status=ClassificationStatus.UNCERTAIN,
                confidence=confidence,
                short_notes=(
                    "The local classifier baseline matched this view, but field validation is incomplete. "
                    "No production identification or library save is allowed yet."
                ),
                sources=("botanika:unvalidated-classifier-baseline",),
                classifier_version=self.classifier_version,
                suggestions=suggestions,
            )

        species_id = self.label_map[best_index]
        species = self._species_by_id.get(species_id)
        if species is None:  # Should be impossible after startup validation.
            return self._failure(ClassificationStatus.ERROR, f"model label is not in the catalog: {species_id}")
        source_urls = tuple(
            self._source_url(source_id)
            for source_id in species.source_ids
            if self._source_url(source_id) is not None
        )
        if not source_urls:
            return self._failure(ClassificationStatus.ERROR, f"species has no usable provenance: {species_id}")
        return ClassificationResult(
            status=ClassificationStatus.ACCEPTED,
            species_id=species.species_id,
            common_name=species.common_name,
            scientific_name=species.scientific_name,
            family=species.family,
            category=species.category,
            conservation_status=species.conservation_status,
            confidence=confidence,
            short_notes=species.short_notes,
            sources=source_urls,
            classifier_version=self.classifier_version,
        )

    def _source_url(self, source_id: str) -> str | None:
        for source in self.catalog.sources:
            if source.source_id == source_id:
                return source.url
        return None

    def _failure(self, status: ClassificationStatus, error: str) -> ClassificationResult:
        return ClassificationResult(
            status=status,
            short_notes="No species identity was produced.",
            classifier_version=self.classifier_version,
            error=error,
        )


class UnavailableSpeciesClassifier:
    """Production-boundary failure object used when an artifact cannot load."""

    is_stub = False

    def __init__(self, error: str) -> None:
        self.classifier_version = "unavailable"
        self.error = str(error)

    def classify(
        self,
        crop: ClassifierInput,
        *,
        cancellation: CancellationToken | None = None,
    ) -> ClassificationResult:
        status = ClassificationStatus.CANCELLED if _cancelled(cancellation) else ClassificationStatus.ERROR
        return ClassificationResult(
            status=status,
            short_notes="No species identity was produced.",
            classifier_version=self.classifier_version,
            error="Species classifier unavailable: " + self.error,
        )


def extract_features(image: np.ndarray) -> np.ndarray:
    """Apply the model's fixed BGR preprocessing and return 14 float features."""

    if not isinstance(image, np.ndarray) or image.ndim != 3 or image.shape[2] != 3:
        raise MalformedImageError("feature extraction expects a 3-channel BGR image")
    if image.dtype != np.uint8 or image.shape[0] <= 0 or image.shape[1] <= 0:
        raise MalformedImageError("feature extraction expects a non-empty uint8 BGR image")
    resized = cv2.resize(image, (96, 96), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV).astype(np.float32)
    hue = hsv[:, :, 0] / 179.0
    saturation = hsv[:, :, 1] / 255.0
    value = hsv[:, :, 2] / 255.0
    green = (hue >= 0.18) & (hue <= 0.50) & (saturation > 0.15) & (value > 0.12)
    yellow = (hue >= 0.10) & (hue < 0.20) & (saturation > 0.20) & (value > 0.18)
    brown = (hue >= 0.02) & (hue < 0.14) & (saturation > 0.20) & (value < 0.70)
    red = ((hue < 0.06) | (hue > 0.94)) & (saturation > 0.25) & (value > 0.18)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 160)
    edge_density = float(np.count_nonzero(edges) / edges.size)
    laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_32F).var())
    texture_score = float(np.clip(laplacian_variance / (laplacian_variance + 500.0), 0.0, 1.0))
    center = green[24:72, 24:72]
    return np.asarray(
        [
            float(hue.mean()),
            float(saturation.mean()),
            float(value.mean()),
            float(hue.std()),
            float(saturation.std()),
            float(value.std()),
            float(green.mean()),
            float(yellow.mean()),
            float(brown.mean()),
            float(red.mean()),
            edge_density,
            texture_score,
            float(np.clip(image.shape[1] / image.shape[0], 0.5, 2.0)),
            float(center.mean()),
        ],
        dtype=np.float32,
    )


def _distance_probabilities(distances: np.ndarray, temperature: float) -> np.ndarray:
    logits = -np.asarray(distances, dtype=np.float64) / max(temperature, 1e-6)
    logits -= float(np.max(logits))
    values = np.exp(np.clip(logits, -80.0, 0.0))
    total = float(values.sum())
    return values / total if total else np.full_like(values, 1.0 / max(1, len(values)))


def _read_model(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassifierError(f"could not read classifier artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ClassifierError("classifier artifact root must be an object")
    return value


def _validate_model(raw: Mapping[str, Any], path: Path, catalog: CatalogDefinition) -> ModelMetadata:
    for key in ("model_id", "version", "runtime", "feature_schema", "label_map", "feature_names", "feature_scales", "centroids", "calibration"):
        if key not in raw:
            raise ClassifierError(f"classifier artifact is missing {key}")
    if raw["feature_schema"] != FEATURE_SCHEMA or tuple(raw["feature_names"]) != FEATURE_NAMES:
        raise ClassifierError("classifier feature preprocessing schema is not supported")
    release = catalog.model_release
    if (
        raw["model_id"] != release.model_id
        or raw["version"] != release.version
        or raw["runtime"] != release.runtime
    ):
        raise ClassifierError("classifier artifact metadata differs from the catalog release")
    if not isinstance(raw["label_map"], Mapping):
        raise ClassifierError("classifier label_map must be an object")
    try:
        label_indices = sorted(int(key) for key in raw["label_map"])
    except (TypeError, ValueError) as exc:
        raise ClassifierError("classifier label_map keys must be integer class indices") from exc
    if label_indices != list(range(len(raw["label_map"]))):
        raise ClassifierError("classifier label_map class indices must be contiguous from zero")
    labels = {str(key): str(value) for key, value in raw["label_map"].items()}
    expected = {str(key): value for key, value in catalog.label_map.items()}
    if labels != expected:
        raise ClassifierError("classifier label map differs from the immutable catalog label map")
    expected_checksum = release.artifact_sha256
    actual_checksum = _sha256(path)
    if expected_checksum and expected_checksum != actual_checksum:
        raise ClassifierError(
            f"classifier artifact checksum mismatch: expected {expected_checksum}, got {actual_checksum}"
        )
    preprocessing = raw.get("input")
    if not isinstance(preprocessing, dict) or preprocessing.get("width") != 96 or preprocessing.get("height") != 96:
        raise ClassifierError("classifier preprocessing must use the declared 96x96 input")
    metrics = dict(catalog.model_release.metrics)
    calibration = raw.get("calibration") if isinstance(raw.get("calibration"), dict) else {}
    provenance = raw.get("provenance") if isinstance(raw.get("provenance"), dict) else {}
    return ModelMetadata(
        model_id=str(raw["model_id"]),
        version=str(raw["version"]),
        runtime=str(raw["runtime"]),
        artifact_path=path.resolve(),
        artifact_sha256=actual_checksum,
        preprocessing=MappingProxyType(dict(preprocessing)),
        metrics=MappingProxyType(dict(metrics)),
        calibration=MappingProxyType(dict(calibration)),
        provenance=MappingProxyType(dict(provenance)),
        deployment_ready=_deployment_ready(metrics, len(labels)),
    )


def _deployment_ready(metrics: Mapping[str, Any], class_count: int) -> bool:
    """Require measured release evidence before production acceptance is possible."""

    macro_f1 = metrics.get("macro_f1")
    unknown_rate = metrics.get("unknown_rejection_rate")
    observations = metrics.get("held_out_observations")
    per_class = metrics.get("per_class")
    benchmark = metrics.get("pi_benchmark")
    numeric = (int, float)

    def bounded(value: Any) -> bool:
        return bool(
            isinstance(value, numeric)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and 0.0 <= float(value) <= 1.0
        )

    def non_negative(value: Any) -> bool:
        return bool(
            isinstance(value, numeric)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and float(value) >= 0.0
        )

    return bool(
        bounded(macro_f1)
        and bounded(unknown_rate)
        and isinstance(observations, int)
        and not isinstance(observations, bool)
        and observations > 0
        and isinstance(per_class, Mapping)
        and len(per_class) == class_count
        and all(
            isinstance(value, Mapping) and bounded(value.get("f1"))
            for value in per_class.values()
        )
        and isinstance(benchmark, Mapping)
        and all(
            non_negative(benchmark.get(key))
            for key in ("latency_p95_ms", "peak_memory_mb", "max_temperature_c")
        )
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ClassifierError(f"could not checksum classifier artifact {path}: {exc}") from exc
    return digest.hexdigest()


# Stable descriptive aliases for callers that do not need to know which
# compact runtime was selected for the current catalog release.
RealSpeciesClassifier = CompactSpeciesClassifier
CatalogFeatureClassifier = CompactSpeciesClassifier
