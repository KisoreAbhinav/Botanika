"""Auditable few-shot campus plant/tree recognition.

Campus labels are intentionally separate from the immutable seven-species
catalog.  A folder such as ``Neem`` becomes the stable ID ``campus:neem`` and
is matched with frozen MobileNetV2 visual embeddings.  Only an explicit,
verified catalog join may attach botanical facts; every other label remains a
plain campus photo label with no invented family, conservation, or ecology
claims.

The enrollment artifact contains source hashes and embeddings so the running
Pi never needs to read the original dataset.  Its self-checksum makes a
partial or modified index fail closed at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import time
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

import cv2
import numpy as np

from botanika.knowledge.catalog import CatalogDefinition, load_catalog, normalize_name
from botanika.knowledge.regional import (
    CampusCatalogView,
    ReferenceCatalog,
    load_reference_catalog,
    merge_catalog_views,
)

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
from .embedding import (
    EmbeddingModelError,
    MobileNetV2Embedder,
    canonical_json,
    load_embedding_model,
    sha256_file,
)


CAMPUS_ARTIFACT_FORMAT = "botanika-campus-fewshot-1"
CAMPUS_MODEL_ID = "botanika.campus.mobilenetv2-prototypes"
CAMPUS_MODEL_VERSION = "campus-fewshot-1.0.0"
DEFAULT_UNKNOWN_SIMILARITY = 0.62
DEFAULT_MINIMUM_MARGIN = 0.06
DEFAULT_PROTOTYPE_WEIGHT = 0.70
DEFAULT_SUGGESTION_LIMIT = 3
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})


class EnrollmentError(ValueError):
    """Raised when an enrollment dataset is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class CampusModelMetadata:
    """Runtime metadata returned to the API capability endpoint."""

    model_id: str
    version: str
    runtime: str
    artifact_path: Path
    artifact_sha256: str
    embedding_model: Mapping[str, Any]
    metrics: Mapping[str, Any]
    calibration: Mapping[str, Any]
    provenance: Mapping[str, Any]
    deployment_ready: bool
    label_count: int
    labels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "version": self.version,
            "runtime": self.runtime,
            "artifact_path": str(self.artifact_path),
            "artifact_sha256": self.artifact_sha256,
            "embedding_model": dict(self.embedding_model),
            "metrics": dict(self.metrics),
            "calibration": dict(self.calibration),
            "provenance": dict(self.provenance),
            "deployment_ready": self.deployment_ready,
            "label_count": self.label_count,
            "labels": list(self.labels),
        }


class CampusFewShotClassifier(SpeciesClassifier):
    """Frozen-embedding prototype classifier for arbitrary campus labels."""

    is_stub = False

    def __init__(
        self,
        artifact_path: Path,
        embedding_model_path: Path,
        catalog_path: Path,
        *,
        regional_catalog_path: Path | None = None,
        acceptance_threshold: float | None = None,
    ) -> None:
        self.artifact_path = Path(artifact_path).expanduser().resolve()
        raw = _read_artifact(self.artifact_path)
        self._raw_artifact = raw
        self._verify_artifact_checksum(raw)
        self.catalog: CatalogDefinition = load_catalog(Path(catalog_path))
        reference = (
            load_reference_catalog(Path(regional_catalog_path))
            if regional_catalog_path is not None
            else None
        )
        self.reference_catalog: ReferenceCatalog | None = reference
        # Keep the seven-class model catalog immutable while allowing a
        # campus artifact to join explicitly reviewed species in the separate
        # regional reference catalog.
        self.catalog_view: CampusCatalogView = merge_catalog_views(self.catalog, reference)
        embedding_raw = raw.get("embedding_model")
        if not isinstance(embedding_raw, Mapping):
            raise ClassifierError("campus artifact embedding_model metadata is missing")
        try:
            self.embedder = load_embedding_model(Path(embedding_model_path), embedding_raw)
        except EmbeddingModelError as exc:
            raise ClassifierError(str(exc)) from exc
        if self.embedder.dimensions != int(embedding_raw.get("embedding_dimensions", -1)):
            raise ClassifierError("campus artifact embedding dimensions do not match model")

        labels = raw.get("labels")
        if not isinstance(labels, list) or not labels:
            raise ClassifierError("campus artifact requires a non-empty labels list")
        self._labels = _validate_labels(labels, self.embedder.dimensions, self.catalog_view)
        self.label_map = MappingProxyType({index: item["label_id"] for index, item in enumerate(self._labels)})
        self._catalog_by_id = self.catalog_view.species_by_id()
        self._validate_catalog_provenance()
        self._prototypes = np.asarray([item["prototype"] for item in self._labels], dtype=np.float32)
        self._samples = [np.asarray(item["embeddings"], dtype=np.float32) for item in self._labels]
        calibration = raw.get("calibration") if isinstance(raw.get("calibration"), Mapping) else {}
        self.unknown_similarity = float(calibration.get("unknown_similarity", DEFAULT_UNKNOWN_SIMILARITY))
        self.minimum_margin = float(calibration.get("minimum_margin", DEFAULT_MINIMUM_MARGIN))
        self.prototype_weight = float(calibration.get("prototype_weight", DEFAULT_PROTOTYPE_WEIGHT))
        self.suggestion_limit = max(1, int(calibration.get("suggestion_limit", DEFAULT_SUGGESTION_LIMIT)))
        self.acceptance_threshold = float(
            acceptance_threshold if acceptance_threshold is not None else calibration.get("acceptance_threshold", 0.58)
        )
        self._metrics = MappingProxyType(dict(raw.get("metrics") or {}))
        self._calibration = MappingProxyType(dict(calibration))
        self._provenance = MappingProxyType(dict(raw.get("provenance") or {}))
        self.classifier_version = str(raw.get("version") or CAMPUS_MODEL_VERSION)
        if not 0.0 <= self.unknown_similarity <= 1.0:
            raise ClassifierError("campus unknown_similarity must be between 0 and 1")
        if not 0.0 <= self.minimum_margin <= 1.0:
            raise ClassifierError("campus minimum_margin must be between 0 and 1")
        if not 0.0 < self.prototype_weight <= 1.0:
            raise ClassifierError("campus prototype_weight must be greater than zero and at most one")
        if not 0.0 <= self.acceptance_threshold <= 1.0:
            raise ClassifierError("campus acceptance_threshold must be between 0 and 1")
        declared_ready = bool(raw.get("deployment_ready", False))
        blocker = _deployment_blocker(self._metrics, self._labels, self._provenance, declared_ready)
        # Never trust a JSON readiness bit by itself.  The effective runtime
        # gate is recomputed from the immutable metrics, label counts, and
        # provenance so a re-signed or hand-edited artifact cannot turn a
        # provisional index into production saves without passing every gate.
        self.deployment_ready = declared_ready and blocker is None
        self.deployment_blocker = blocker
        self._metadata = CampusModelMetadata(
            model_id=str(raw.get("model_id") or CAMPUS_MODEL_ID),
            version=self.classifier_version,
            runtime=str(raw.get("runtime") or "onnxruntime-prototype-search"),
            artifact_path=self.artifact_path,
            artifact_sha256=str(raw["artifact_sha256"]),
            embedding_model=MappingProxyType(dict(embedding_raw)),
            metrics=self._metrics,
            calibration=self._calibration,
            provenance=self._provenance,
            deployment_ready=self.deployment_ready,
            label_count=len(self._labels),
            labels=tuple(str(item["display_name"]) for item in self._labels),
        )

    def _validate_catalog_provenance(self) -> None:
        """Fail closed if an artifact is used with a different catalog.

        A campus artifact stores catalog joins by immutable species ID.  The
        facts shown for those joins are therefore only safe when the exact
        catalog revision used at enrollment is present at runtime.  The
        regional catalog is optional for arbitrary campus labels, but becomes
        mandatory when the artifact contains a regional join.
        """

        provenance = self._raw_artifact.get("provenance")
        if not isinstance(provenance, Mapping):
            raise ClassifierError("campus artifact provenance is missing")

        expected_primary = {
            "catalog_id": self.catalog.catalog_id,
            "catalog_version": self.catalog.version,
            "catalog_digest": self.catalog.digest,
        }
        for field, expected in expected_primary.items():
            actual = str(provenance.get(field) or "")
            if actual != expected:
                raise ClassifierError(
                    f"campus artifact {field} mismatch: expected {expected}, got {actual or '<missing>'}"
                )

        joined = {
            str(item.get("catalog_species_id"))
            for item in self._labels
            if item.get("catalog_species_id")
        }
        primary_ids = set(self.catalog.species_by_id())
        regional_joined = joined - primary_ids
        if not regional_joined:
            return
        if self.reference_catalog is None:
            raise ClassifierError("campus artifact contains regional catalog joins but no regional catalog is configured")
        reference = provenance.get("reference_catalog")
        if not isinstance(reference, Mapping):
            raise ClassifierError("campus artifact contains regional joins but reference catalog provenance is missing")
        expected_regional = {
            "catalog_id": self.reference_catalog.catalog_id,
            "version": self.reference_catalog.version,
            "digest": self.reference_catalog.digest,
        }
        for field, expected in expected_regional.items():
            actual = str(reference.get(field) or "")
            if actual != expected:
                raise ClassifierError(
                    f"campus artifact reference catalog {field} mismatch: expected {expected}, got {actual or '<missing>'}"
                )

    @property
    def metadata(self) -> CampusModelMetadata:
        return self._metadata

    @property
    def classifier_model(self) -> dict[str, Any]:
        return self._metadata.to_dict()

    @property
    def model_release(self) -> dict[str, Any]:
        return self._metadata.to_dict()

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
            embedding = self.embedder.embed_views(image)
        except MalformedImageError as exc:
            return self._failure(ClassificationStatus.MALFORMED_IMAGE, str(exc))
        except (EmbeddingModelError, ValueError, cv2.error) as exc:
            return self._failure(ClassificationStatus.ERROR, f"campus embedding failed: {exc}")
        if _cancelled(cancellation):
            return self._failure(ClassificationStatus.CANCELLED, "Classification cancelled after embedding")

        scores = score_labels(embedding, self._prototypes, self._samples, self.prototype_weight)
        order = np.argsort(-scores)
        best = int(order[0])
        best_score = float(scores[best])
        confidence = float(np.clip((best_score - self.unknown_similarity) / max(1e-6, 1.0 - self.unknown_similarity), 0.0, 1.0))
        suggestions = tuple(self._suggestion(int(index), float(scores[int(index)])) for index in order[: self.suggestion_limit])
        accepted = accepted_label_index(
            scores,
            {
                "unknown_similarity": self.unknown_similarity,
                "minimum_margin": self.minimum_margin,
                "acceptance_threshold": self.acceptance_threshold,
            },
        )
        if accepted is None or not self.deployment_ready:
            if accepted is None:
                note = (
                    "This view is outside the confident campus-label range or is too close to another label. "
                    "Try a clear leaf, flower, fruit, bark, or whole-plant view."
                )
                if not self.deployment_ready:
                    note += " The enrolled index is also provisional, so saves remain disabled until validation is complete."
                validation_pending = False
            else:
                note = (
                    "Campus labels are enrolled and suggestions are available, but this index is not production-validated. "
                    "Supply independent held-out images and unknown images before enabling saves."
                )
                validation_pending = True
            return ClassificationResult(
                status=ClassificationStatus.UNCERTAIN,
                confidence=confidence,
                short_notes=note,
                sources=("botanika:campus-fewshot-enrollment",),
                classifier_version=self.classifier_version,
                suggestions=suggestions,
                validation_pending=validation_pending,
            )

        label = self._labels[best]
        catalog_id = label.get("catalog_species_id")
        if catalog_id:
            species = self._catalog_by_id.get(str(catalog_id))
            if species is None:
                return self._failure(ClassificationStatus.ERROR, f"campus artifact catalog label is missing: {catalog_id}")
            source_urls = tuple(
                source.url
                for source in self.catalog_view.sources
                if source.source_id in species.source_ids
            )
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
                sources=source_urls or ("botanika:catalog-join",),
                classifier_version=self.classifier_version,
                catalogued=True,
            )

        # An arbitrary campus label is accepted only after the same evidence
        # gate, but its fields explicitly say that no botanical facts exist.
        # This keeps it storable/displayable without fabricating taxonomy.
        display_name = str(label["display_name"])
        return ClassificationResult(
            status=ClassificationStatus.ACCEPTED,
            species_id=str(label["label_id"]),
            common_name=display_name,
            scientific_name="Uncatalogued campus label",
            family="Not catalogued",
            category="Campus enrolled label",
            conservation_status="Not assessed",
            confidence=confidence,
            short_notes=(
                "Recognized from campus enrollment photos. No sourced botanical facts are attached to this label."
            ),
            sources=("botanika:campus-fewshot-enrollment",),
            classifier_version=self.classifier_version,
            catalogued=False,
        )

    def _suggestion(self, index: int, score: float) -> SpeciesSuggestion:
        label = self._labels[index]
        confidence = float(np.clip((score - self.unknown_similarity) / max(1e-6, 1.0 - self.unknown_similarity), 0.0, 1.0))
        if label.get("catalog_species_id"):
            species = self._catalog_by_id[str(label["catalog_species_id"])]
            return SpeciesSuggestion(
                common_name=species.common_name,
                scientific_name=species.scientific_name,
                confidence=confidence,
                catalogued=True,
            )
        return SpeciesSuggestion(
            common_name=str(label["display_name"]),
            scientific_name="Uncatalogued campus label",
            confidence=confidence,
            catalogued=False,
        )

    def _failure(self, status: ClassificationStatus, error: str) -> ClassificationResult:
        return ClassificationResult(
            status=status,
            short_notes="No plant identity was produced.",
            classifier_version=self.classifier_version,
            error=error,
        )

    def _verify_artifact_checksum(self, raw: Mapping[str, Any]) -> None:
        expected = str(raw.get("artifact_sha256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ClassifierError("campus artifact must contain a lowercase SHA-256")
        payload = {key: value for key, value in raw.items() if key != "artifact_sha256"}
        actual = hashlib.sha256(canonical_json(payload)).hexdigest()
        if actual != expected:
            raise ClassifierError(f"campus artifact checksum mismatch: expected {expected}, got {actual}")


def score_labels(
    embedding: np.ndarray,
    prototypes: np.ndarray,
    samples: Sequence[np.ndarray],
    prototype_weight: float = DEFAULT_PROTOTYPE_WEIGHT,
) -> np.ndarray:
    """Combine prototype and nearest enrolled-photo cosine similarity."""

    query = np.asarray(embedding, dtype=np.float32).reshape(-1)
    query = query / max(1e-8, float(np.linalg.norm(query)))
    proto = np.asarray(prototypes, dtype=np.float32)
    proto = proto / np.maximum(1e-8, np.linalg.norm(proto, axis=1, keepdims=True))
    prototype_scores = proto @ query
    nearest_scores = np.asarray(
        [float(np.max(np.asarray(vectors, dtype=np.float32) @ query)) for vectors in samples],
        dtype=np.float32,
    )
    weight = float(np.clip(prototype_weight, 0.0, 1.0))
    return np.asarray(weight * prototype_scores + (1.0 - weight) * nearest_scores, dtype=np.float32)


def accepted_label_index(
    scores: np.ndarray,
    calibration: Mapping[str, Any],
) -> int | None:
    """Apply the same similarity, margin, and confidence gate as runtime."""

    values = np.asarray(scores, dtype=np.float32).reshape(-1)
    if values.size < 2 or not np.all(np.isfinite(values)):
        return None
    order = np.argsort(-values)
    best = int(order[0])
    second = int(order[1])
    best_score = float(values[best])
    margin = best_score - float(values[second])
    unknown_similarity = float(calibration["unknown_similarity"])
    confidence = float(
        np.clip(
            (best_score - unknown_similarity) / max(1e-6, 1.0 - unknown_similarity),
            0.0,
            1.0,
        )
    )
    if (
        best_score < unknown_similarity
        or margin < float(calibration["minimum_margin"])
        or confidence < float(calibration["acceptance_threshold"])
    ):
        return None
    return best


def build_enrollment_artifact(
    dataset_dir: Path,
    output_path: Path,
    *,
    embedding_model_path: Path,
    catalog_path: Path,
    regional_catalog_path: Path | None = None,
    held_out_dir: Path | None = None,
    unknown_dir: Path | None = None,
    catalog_map: Mapping[str, str] | None = None,
    min_images_per_label: int = 3,
    approve_production: bool = False,
) -> dict[str, Any]:
    """Enroll one or many labels and atomically write a checksummed artifact."""

    root = Path(dataset_dir).expanduser().resolve()
    if not root.is_dir():
        raise EnrollmentError(f"dataset directory does not exist: {root}")
    if min_images_per_label < 2:
        raise EnrollmentError("at least two enrollment images per label are required")
    catalog = load_catalog(Path(catalog_path))
    reference = (
        load_reference_catalog(Path(regional_catalog_path))
        if regional_catalog_path is not None
        else None
    )
    catalog_view = merge_catalog_views(catalog, reference)
    # Only the reviewed, penultimate-feature export is supported.  Do not
    # silently build an artifact against an arbitrary ONNX file.
    try:
        embedder = MobileNetV2Embedder(Path(embedding_model_path))
    except EmbeddingModelError as exc:
        raise EnrollmentError(f"could not load reviewed embedding model: {exc}") from exc

    train = _collect_split(root, split_name="train")
    if len(train) == 0:
        raise EnrollmentError("dataset must contain at least one non-empty label directory")
    for label, files in train.items():
        if len(files) < min_images_per_label:
            raise EnrollmentError(f"label {label!r} has {len(files)} images; need at least {min_images_per_label}")
    heldout = _collect_split(Path(held_out_dir).expanduser().resolve(), split_name="held-out") if held_out_dir else {}
    unexpected_heldout = sorted(set(heldout) - set(train), key=str.casefold)
    if unexpected_heldout:
        raise EnrollmentError(
            "held-out labels are absent from training: " + ", ".join(unexpected_heldout)
        )
    unknown_files = _collect_unknown(Path(unknown_dir).expanduser().resolve()) if unknown_dir else []

    all_records = _embed_split(train, embedder, split_name="train", root=root)
    heldout_records = _embed_split(heldout, embedder, split_name="held-out", root=Path(held_out_dir).expanduser().resolve()) if heldout else {}
    unknown_records = _embed_files(unknown_files, embedder, split_name="unknown", root=Path(unknown_dir).expanduser().resolve()) if unknown_files else []
    duplicates = _find_duplicates([item for values in all_records.values() for item in values] + [item for values in heldout_records.values() for item in values] + unknown_records)
    if duplicates:
        sample = duplicates[0]
        raise EnrollmentError(
            "duplicate or near-duplicate images cross the enrollment/evaluation boundary: "
            f"{sample[0]} and {sample[1]} (hamming distance {sample[2]})"
        )

    labels = []
    for label_name in sorted(all_records, key=str.casefold):
        label_id = campus_label_id(label_name)
        matched = _catalog_join(label_name, catalog_view, catalog_map or {})
        records = all_records[label_name]
        vectors = np.asarray([item["embedding"] for item in records], dtype=np.float32)
        prototype = _unit(vectors.mean(axis=0))
        labels.append(
            {
                "label_id": label_id,
                "display_name": label_name,
                "aliases": [label_name],
                "catalog_species_id": matched,
                "sample_count": len(records),
                "prototype": [float(value) for value in prototype],
                "embeddings": [[float(value) for value in item["embedding"]] for item in records],
                "samples": [
                    {
                        "relative_path": item["relative_path"],
                        "sha256": item["sha256"],
                        "perceptual_hash": item["perceptual_hash"],
                    }
                    for item in records
                ],
            }
        )

    calibration = {
        "unknown_similarity": DEFAULT_UNKNOWN_SIMILARITY,
        "minimum_margin": DEFAULT_MINIMUM_MARGIN,
        "prototype_weight": DEFAULT_PROTOTYPE_WEIGHT,
        "acceptance_threshold": 0.58,
        "suggestion_limit": DEFAULT_SUGGESTION_LIMIT,
        "query_views": ["original", "horizontal_flip"],
    }
    metrics = _evaluate(
        labels,
        all_records,
        heldout_records,
        unknown_records,
        calibration,
        embedder,
    )
    provenance = {
        "enrollment_format": CAMPUS_ARTIFACT_FORMAT,
        "dataset_root": str(root),
        "training_split": "label folders under dataset_root",
        "held_out_root": str(Path(held_out_dir).expanduser().resolve()) if held_out_dir else None,
        "unknown_root": str(Path(unknown_dir).expanduser().resolve()) if unknown_dir else None,
        "catalog_id": catalog.catalog_id,
        "catalog_version": catalog.version,
        "catalog_digest": catalog.digest,
        "reference_catalog": (
            {
                "catalog_id": reference.catalog_id,
                "version": reference.version,
                "region": reference.region,
                "digest": reference.digest,
                "species_count": len(reference.species),
            }
            if reference is not None
            else None
        ),
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "held_out_group_counts": _heldout_group_counts(Path(held_out_dir).expanduser().resolve(), set(train)) if held_out_dir else {},
        "independent_plant_ids_available": _has_nested_groups(Path(held_out_dir).expanduser().resolve(), set(train)) if held_out_dir else False,
        "leakage_note": (
            "The tool checks exact and perceptual duplicates. It cannot infer whether two photographs show the same physical plant; "
            "use plant/session-separated folders for held-out evidence."
        ),
        "license_note": "Enrollment image rights remain with the operator; record licenses/consent outside this binary artifact.",
    }
    # The provenance flag is part of the release gate.  An operator may still
    # build and use the provisional suggestions without pretending that five
    # views of one plant generalise to an entire species/label.
    if not provenance["independent_plant_ids_available"]:
        metrics["deployment_blockers"].append(
            "held-out folders must identify at least three independent plants/sessions per label; five views of one plant are not independent evidence"
        )
    deployment_gate = _deployment_gate(metrics, labels, approve_production)
    artifact: dict[str, Any] = {
        "format": CAMPUS_ARTIFACT_FORMAT,
        "model_id": CAMPUS_MODEL_ID,
        "version": CAMPUS_MODEL_VERSION,
        "runtime": "onnxruntime-prototype-search",
        "embedding_model": embedder.metadata.to_dict(),
        "input": {
            "width": embedder.metadata.input_width,
            "height": embedder.metadata.input_height,
            "channels": 3,
            "color_order": "BGR input converted to RGB",
        },
        "labels": labels,
        "calibration": calibration,
        "metrics": metrics,
        "provenance": provenance,
        "deployment_ready": deployment_gate,
        "deployment_gate": {
            "approved_by_operator": bool(approve_production),
            "requirements": [
                "at least five enrollment images per label",
                "at least three independent held-out images per label",
                "at least five unknown images",
                "held-out macro-F1 >= 0.80",
                "unknown rejection rate >= 0.80",
                "no exact or perceptual duplicates across splits",
                "explicit operator approval flag",
                "held-out folders identify at least three plant/session groups per label",
            ],
            "blockers": list(metrics.get("deployment_blockers", [])),
        },
    }
    artifact["artifact_sha256"] = hashlib.sha256(canonical_json(artifact)).hexdigest()
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp-{int(time.time() * 1000)}")
    temporary.write_bytes(json.dumps(artifact, sort_keys=True, indent=2, ensure_ascii=False).encode("utf-8"))
    temporary.replace(output)
    checksum_path = output.with_suffix(output.suffix + ".sha256")
    checksum_path.write_text(f"{artifact['artifact_sha256']}  {output.name}\n", encoding="utf-8")
    return artifact


def campus_label_id(display_name: str) -> str:
    """Create a stable, path-safe ID without pretending it is taxonomy."""

    normalized = unicodedata.normalize("NFKD", str(display_name)).encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if not slug:
        raise EnrollmentError(f"label {display_name!r} has no usable ASCII ID")
    return f"campus:{slug}"


def _read_artifact(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClassifierError(f"could not read campus classifier artifact {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("format") != CAMPUS_ARTIFACT_FORMAT:
        raise ClassifierError(f"unsupported campus classifier artifact: {path}")
    return raw


def _validate_labels(labels: list[Any], dimensions: int, catalog: CampusCatalogView) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    label_ids: set[str] = set()
    hashes: set[str] = set()
    catalog_ids = set(catalog.species_by_id())
    for item in labels:
        if not isinstance(item, Mapping):
            raise ClassifierError("campus label entries must be objects")
        label_id = str(item.get("label_id") or "").strip()
        display = str(item.get("display_name") or "").strip()
        if not label_id or not display or label_id in label_ids:
            raise ClassifierError("campus label IDs and names must be non-empty and unique")
        if not re.fullmatch(r"campus:[a-z0-9][a-z0-9-]*", label_id):
            raise ClassifierError(f"unsafe campus label ID: {label_id}")
        label_ids.add(label_id)
        catalog_id = item.get("catalog_species_id")
        if catalog_id is not None and str(catalog_id) not in catalog_ids:
            raise ClassifierError(f"campus label joins unknown catalog species: {catalog_id}")
        prototype = np.asarray(item.get("prototype"), dtype=np.float32).reshape(-1)
        embeddings = np.asarray(item.get("embeddings"), dtype=np.float32)
        if prototype.size != dimensions or embeddings.ndim != 2 or embeddings.shape[1] != dimensions or embeddings.shape[0] < 2:
            raise ClassifierError(f"campus label {display!r} has invalid embedding dimensions")
        if not np.all(np.isfinite(prototype)) or not np.all(np.isfinite(embeddings)):
            raise ClassifierError(f"campus label {display!r} has non-finite embeddings")
        sample_count = item.get("sample_count")
        if (
            isinstance(sample_count, bool)
            or not isinstance(sample_count, int)
            or sample_count != int(embeddings.shape[0])
        ):
            raise ClassifierError(
                f"campus label {display!r} sample_count does not match embeddings"
            )
        sample_entries = item.get("samples")
        if not isinstance(sample_entries, list) or len(sample_entries) != embeddings.shape[0]:
            raise ClassifierError(f"campus label {display!r} samples do not match embeddings")
        for sample in sample_entries:
            if not isinstance(sample, Mapping) or not re.fullmatch(r"[0-9a-f]{64}", str(sample.get("sha256") or "")):
                raise ClassifierError(f"campus label {display!r} has invalid source hash")
            digest = str(sample["sha256"])
            if digest in hashes:
                raise ClassifierError("campus artifact contains duplicate source images")
            hashes.add(digest)
        values.append(
            {
                "label_id": label_id,
                "display_name": display,
                "catalog_species_id": str(catalog_id) if catalog_id else None,
                "prototype": _unit(prototype),
                "embeddings": np.asarray([_unit(vector) for vector in embeddings], dtype=np.float32),
                "samples": sample_entries,
            }
        )
    return values


def _deployment_blocker(
    metrics: Mapping[str, Any],
    labels: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any],
    declared_ready: bool,
) -> str | None:
    """Recompute the release gate from artifact evidence, not its ready bit."""

    blockers = _recomputed_deployment_blockers(metrics, labels, provenance)
    if declared_ready and not blockers:
        return None
    if blockers:
        return "; ".join(blockers)
    return "Campus enrollment requires independent held-out and unknown-image evidence before production saves are enabled."


def _recomputed_deployment_blockers(
    metrics: Mapping[str, Any],
    labels: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any],
) -> list[str]:
    """Validate all promotion requirements again when loading an artifact."""

    values: list[str] = []

    def add(message: str) -> None:
        if message not in values:
            values.append(message)

    recorded = metrics.get("deployment_blockers")
    if isinstance(recorded, list):
        for item in recorded:
            text = str(item).strip()
            if text:
                add(text)
    if any(int(label.get("sample_count", 0)) < 5 for label in labels):
        add("each label needs at least five enrollment images")

    heldout = metrics.get("held_out")
    per_class = heldout.get("per_class") if isinstance(heldout, Mapping) else None
    if not isinstance(per_class, Mapping) or any(
        not isinstance(per_class.get(str(label.get("display_name"))), Mapping)
        or int(per_class[str(label.get("display_name"))].get("support", 0)) < 3
        for label in labels
    ):
        add("each label needs at least three independent held-out images")
    if int(metrics.get("unknown_observations", 0) or 0) < 5:
        add("at least five unknown images are required")
    macro_f1 = metrics.get("macro_f1")
    if macro_f1 is None or float(macro_f1) < 0.80:
        add("held-out macro-F1 must be at least 0.80")
    unknown_rate = metrics.get("unknown_rejection_rate")
    if unknown_rate is None or float(unknown_rate) < 0.80:
        add("unknown rejection rate must be at least 0.80")
    benchmark = metrics.get("pi_benchmark")
    if not isinstance(benchmark, Mapping) or benchmark.get("latency_p95_ms") is None:
        add("a live CPU embedding benchmark is required")
    group_counts = provenance.get("held_out_group_counts")
    groups_valid = isinstance(group_counts, Mapping) and all(
        int(group_counts.get(str(label.get("display_name")), 0) or 0) >= 3
        for label in labels
    )
    if provenance.get("independent_plant_ids_available") is not True or not groups_valid:
        add(
            "held-out folders must identify at least three independent plants/sessions per label; "
            "five views of one plant are not independent evidence"
        )
    return values


def _deployment_gate(metrics: Mapping[str, Any], labels: Sequence[Mapping[str, Any]], approved: bool) -> bool:
    blockers = metrics.get("deployment_blockers")
    return bool(approved and isinstance(blockers, list) and not blockers)


def _collect_split(root: Path, *, split_name: str) -> dict[str, list[Path]]:
    if not root.is_dir():
        raise EnrollmentError(f"{split_name} directory does not exist: {root}")
    result: dict[str, list[Path]] = {}
    for child in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        if child.name.startswith("."):
            continue
        if not child.is_dir():
            continue
        files = [path for path in sorted(child.rglob("*")) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
        if files:
            result[child.name] = files
    return result


def _collect_unknown(root: Path) -> list[Path]:
    if not root.is_dir():
        raise EnrollmentError(f"unknown directory does not exist: {root}")
    return [path for path in sorted(root.rglob("*")) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]


def _embed_split(groups: Mapping[str, Sequence[Path]], embedder: MobileNetV2Embedder, *, split_name: str, root: Path) -> dict[str, list[dict[str, Any]]]:
    return {label: _embed_files(files, embedder, split_name=split_name, root=root) for label, files in groups.items()}


def _embed_files(files: Sequence[Path], embedder: MobileNetV2Embedder, *, split_name: str, root: Path) -> list[dict[str, Any]]:
    result = []
    for path in files:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise EnrollmentError(f"could not decode {split_name} image: {path}")
        try:
            embedding = embedder.embed_views(image)
        except EmbeddingModelError as exc:
            raise EnrollmentError(f"could not embed {split_name} image {path}: {exc}") from exc
        result.append(
            {
                "relative_path": path.resolve().relative_to(root.resolve()).as_posix(),
                "sha256": sha256_file(path),
                "perceptual_hash": perceptual_hash(image),
                "embedding": embedding,
                "label": path.parent.name,
                "split": split_name,
                "source_path": str(path.resolve()),
            }
        )
    return result


def perceptual_hash(image: np.ndarray) -> str:
    """Return a deterministic 64-bit dHash for duplicate/leakage checks."""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    bits = (resized[:, 1:] >= resized[:, :-1]).reshape(-1)
    value = 0
    for bit in bits:
        value = (value << 1) | int(bool(bit))
    return f"{value:016x}"


def _find_duplicates(records: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, int]]:
    seen_hash: dict[str, str] = {}
    seen_phash: list[tuple[str, str]] = []
    duplicates: list[tuple[str, str, int]] = []
    for item in records:
        path = str(item["relative_path"])
        digest = str(item["sha256"])
        previous = seen_hash.get(digest)
        if previous is not None:
            duplicates.append((previous, path, 0))
        seen_hash[digest] = path
        current = int(str(item["perceptual_hash"]), 16)
        for old_path, old_hash in seen_phash:
            distance = (current ^ int(old_hash, 16)).bit_count()
            if distance <= 5:
                duplicates.append((old_path, path, distance))
        seen_phash.append((path, str(item["perceptual_hash"])))
    return duplicates


def _catalog_join(label: str, catalog: CampusCatalogView, explicit: Mapping[str, str]) -> str | None:
    explicit_value = explicit.get(label)
    if explicit_value is not None:
        if explicit_value not in catalog.species_by_id():
            raise EnrollmentError(f"catalog map for {label!r} points to unknown species {explicit_value!r}")
        return str(explicit_value)
    normalized = normalize_name(label)
    for species in catalog.species:
        names = (species.common_name, species.scientific_name, *species.aliases)
        if normalized and any(normalized == normalize_name(name) for name in names):
            return species.species_id
    return None


def _evaluate(labels: Sequence[Mapping[str, Any]], train: Mapping[str, Sequence[Mapping[str, Any]]], heldout: Mapping[str, Sequence[Mapping[str, Any]]], unknown: Sequence[Mapping[str, Any]], calibration: Mapping[str, Any], embedder: MobileNetV2Embedder) -> dict[str, Any]:
    prototypes = np.asarray([label["prototype"] for label in labels], dtype=np.float32)
    samples = [np.asarray(label["embeddings"], dtype=np.float32) for label in labels]
    names = [str(label["display_name"]) for label in labels]
    loo_predictions: list[tuple[str, str, float]] = []
    for label_index, label in enumerate(labels):
        vectors = samples[label_index]
        for sample_index, query in enumerate(vectors):
            reduced = [np.delete(other, sample_index, axis=0) if idx == label_index else other for idx, other in enumerate(samples)]
            reduced_proto = [_unit(np.delete(vectors, sample_index, axis=0).mean(axis=0)) if idx == label_index else _unit(other.mean(axis=0)) for idx, other in enumerate(samples)]
            scores = score_labels(query, np.asarray(reduced_proto), reduced, float(calibration["prototype_weight"]))
            accepted = accepted_label_index(scores, calibration)
            predicted = names[accepted] if accepted is not None else "__unknown__"
            loo_predictions.append((names[label_index], predicted, float(np.max(scores))))
    loo = _classification_metrics(loo_predictions, names)

    heldout_predictions: list[tuple[str, str, float]] = []
    for label, records in heldout.items():
        for record in records:
            scores = score_labels(record["embedding"], prototypes, samples, float(calibration["prototype_weight"]))
            winner = accepted_label_index(scores, calibration)
            predicted = names[winner] if winner is not None else "__unknown__"
            heldout_predictions.append((label, predicted, float(np.max(scores))))
    heldout_metrics = _classification_metrics(heldout_predictions, names)
    unknown_scores: list[float] = []
    rejected = 0
    for record in unknown:
        scores = score_labels(record["embedding"], prototypes, samples, float(calibration["prototype_weight"]))
        unknown_scores.append(float(np.max(scores)))
        if accepted_label_index(scores, calibration) is None:
            rejected += 1
    unknown_rate = (rejected / len(unknown_scores)) if unknown_scores else None

    blockers: list[str] = []
    if any(int(label["sample_count"]) < 5 for label in labels):
        blockers.append("each label needs at least five enrollment images")
    if any(sum(1 for item in heldout.get(str(label["display_name"]), ())) < 3 for label in labels):
        blockers.append("each label needs at least three independent held-out images")
    if len(unknown) < 5:
        blockers.append("at least five unknown images are required")
    if heldout_metrics["macro_f1"] is None or float(heldout_metrics["macro_f1"]) < 0.80:
        blockers.append("held-out macro-F1 must be at least 0.80")
    if unknown_rate is None or unknown_rate < 0.80:
        blockers.append("unknown rejection rate must be at least 0.80")
    benchmark = _benchmark(embedder, [item for values in train.values() for item in values])
    if benchmark.get("latency_p95_ms") is None:
        blockers.append("a live CPU embedding benchmark is required")
    return {
        "evaluation_status": "held-out-and-unknown" if heldout_predictions and unknown_scores else "enrollment-only",
        "training_observations": sum(len(values) for values in train.values()),
        "held_out_observations": len(heldout_predictions),
        "unknown_observations": len(unknown_scores),
        "leave_one_out": loo,
        "held_out": heldout_metrics,
        "macro_f1": heldout_metrics.get("macro_f1"),
        "unknown_rejection_rate": unknown_rate,
        "per_class": heldout_metrics.get("per_class", {}),
        "unknown_score_max": max(unknown_scores) if unknown_scores else None,
        "pi_benchmark": benchmark,
        "leakage": {
            "exact_hash_duplicates": 0,
            "perceptual_duplicate_hamming_threshold": 5,
            "plant_identity_split_verified": False,
        },
        "deployment_blockers": blockers,
    }


def _classification_metrics(predictions: Sequence[tuple[str, str, float]], names: Sequence[str]) -> dict[str, Any]:
    if not predictions:
        return {
            "observations": 0,
            "accuracy": None,
            "accepted_accuracy": None,
            "coverage": None,
            "abstentions": 0,
            "wrong_label": 0,
            "macro_f1": None,
            "per_class": {},
        }
    per_class: dict[str, dict[str, float | int]] = {}
    for name in names:
        tp = sum(actual == name and predicted == name for actual, predicted, _ in predictions)
        fp = sum(actual != name and predicted == name for actual, predicted, _ in predictions)
        fn = sum(actual == name and predicted != name for actual, predicted, _ in predictions)
        support = sum(actual == name for actual, _, _ in predictions)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[name] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
    accuracy = sum(actual == predicted for actual, predicted, _ in predictions) / len(predictions)
    abstentions = sum(predicted == "__unknown__" for _, predicted, _ in predictions)
    wrong_label = sum(
        predicted != actual and predicted != "__unknown__"
        for actual, predicted, _ in predictions
    )
    accepted = len(predictions) - abstentions
    return {
        "observations": len(predictions),
        "accuracy": accuracy,
        # These selective metrics make a provisional index auditable: a low
        # overall score can be caused by honest abstention rather than a
        # confident wrong species.  They are still not independent evidence.
        "accepted_accuracy": sum(actual == predicted for actual, predicted, _ in predictions) / accepted
        if accepted
        else None,
        "coverage": accepted / len(predictions),
        "abstentions": abstentions,
        "wrong_label": wrong_label,
        "macro_f1": sum(float(item["f1"]) for item in per_class.values()) / len(per_class),
        "per_class": per_class,
    }


def _benchmark(embedder: MobileNetV2Embedder, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    # Enrollment already computed vectors; benchmark the actual Pi path on a
    # bounded number of source images, keeping the artifact generation cheap.
    timings: list[float] = []
    start_memory = _rss_mb()
    for record in list(records)[: min(8, len(records))]:
        source_path = record.get("source_path")
        if not source_path:
            continue
        image = cv2.imread(str(source_path), cv2.IMREAD_COLOR)
        if image is None:
            continue
        started = time.perf_counter()
        embedder.embed_views(image)
        timings.append((time.perf_counter() - started) * 1000.0)
    timings.sort()

    def percentile(percent: float) -> float | None:
        if not timings:
            return None
        index = min(len(timings) - 1, max(0, math.ceil((percent / 100.0) * len(timings)) - 1))
        return round(float(timings[index]), 2)

    return {
        "samples": len(timings),
        "latency_p50_ms": percentile(50),
        "latency_p95_ms": percentile(95),
        "peak_memory_mb": start_memory,
        "max_temperature_c": _temperature_c(),
        "note": "Build-time CPU embedding timing; repeat with tools/verify_models.py on the production Pi after enrollment.",
    }


def _rss_mb() -> float | None:
    try:
        import resource

        value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux reports KiB; macOS reports bytes. 
        return round(value / 1024.0 if value > 10_000 else value / (1024.0 * 1024.0), 2)
    except Exception:
        return None


def _temperature_c() -> float | None:
    candidates = sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
    for path in candidates:
        try:
            return round(float(path.read_text().strip()) / 1000.0, 2)
        except (OSError, ValueError):
            continue
    return None


def _has_nested_groups(root: Path, labels: set[str]) -> bool:
    """Require at least three plant/session groups under every held-out label."""

    if not root.is_dir() or not labels:
        return False
    for label in labels:
        folder = root / label
        if not folder.is_dir():
            return False
        nested = [
            child
            for child in folder.iterdir()
            if child.is_dir()
            and not child.name.startswith(".")
            and any(
                path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
                for path in child.rglob("*")
            )
        ]
        if len(nested) < 3:
            return False
    return True


def _heldout_group_counts(root: Path, labels: set[str]) -> dict[str, int]:
    """Return the number of explicit held-out plant/session folders per label."""

    if not root.is_dir():
        return {label: 0 for label in sorted(labels)}
    counts: dict[str, int] = {}
    for label in sorted(labels):
        folder = root / label
        counts[label] = sum(
            1
            for child in folder.iterdir()
            if child.is_dir()
            and not child.name.startswith(".")
            and any(
                path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
                for path in child.rglob("*")
            )
        ) if folder.is_dir() else 0
    return counts


def _unit(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(value))
    if not math.isfinite(norm) or norm <= 1e-8:
        raise EnrollmentError("cannot normalize a zero/non-finite embedding")
    return np.asarray(value / norm, dtype=np.float32)
