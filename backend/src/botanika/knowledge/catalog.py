"""Validated, immutable catalog inputs used by the Phase 6 runtime.

The catalog is source data, not frontend content.  A stable ID and immutable
label map are required before the classifier may turn a model index into a
species identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping


class CatalogIntegrityError(ValueError):
    """Raised when catalog metadata is incomplete, duplicated, or inconsistent."""


def normalize_name(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", value.lower()).split())


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    title: str
    publisher: str
    url: str
    license: str
    license_url: str | None
    retrieved_at: str | None
    checksum: str | None
    source_type: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceRecord":
        if not isinstance(value, Mapping):
            raise CatalogIntegrityError("source entries must be objects")
        required = ("source_id", "title", "publisher", "url", "license")
        if any(not isinstance(value.get(key), str) or not value[key].strip() for key in required):
            raise CatalogIntegrityError("sources require IDs, title, publisher, URL, and license")
        return cls(
            source_id=value["source_id"].strip(),
            title=value["title"].strip(),
            publisher=value["publisher"].strip(),
            url=value["url"].strip(),
            license=value["license"].strip(),
            license_url=_optional_string(value.get("license_url")),
            retrieved_at=_optional_string(value.get("retrieved_at")),
            checksum=_optional_string(value.get("checksum")),
            source_type=str(value.get("source_type") or "reference").strip(),
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "publisher": self.publisher,
            "url": self.url,
            "license": self.license,
            "license_url": self.license_url,
            "retrieved_at": self.retrieved_at,
            "checksum": self.checksum,
            "source_type": self.source_type,
        }


@dataclass(frozen=True, slots=True)
class ConservationAssessment:
    authority: str
    status: str
    assessment_url: str | None = None
    assessed_at: str | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeSeed:
    text: str
    source_id: str
    kind: str = "fact"


@dataclass(frozen=True, slots=True)
class SpeciesRecord:
    species_id: str
    scientific_name: str
    common_name: str
    family: str
    region: str
    category: str
    native_status: str
    is_native: bool
    conservation_status: str
    ecology: str
    short_notes: str
    aliases: tuple[str, ...]
    image_views: tuple[str, ...]
    image_source_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    assessments: tuple[ConservationAssessment, ...]
    knowledge: tuple[KnowledgeSeed, ...]

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], source_ids: set[str]) -> "SpeciesRecord":
        if not isinstance(value, Mapping):
            raise CatalogIntegrityError("species entries must be objects")
        fields = (
            "species_id", "scientific_name", "common_name", "family", "region",
            "category", "native_status", "conservation_status", "ecology", "short_notes",
        )
        if any(not isinstance(value.get(key), str) or not value[key].strip() for key in fields):
            raise CatalogIntegrityError("species entries require complete stable metadata")
        species_id = value["species_id"].strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]+", species_id):
            raise CatalogIntegrityError(f"invalid stable species ID: {species_id!r}")
        aliases = _string_tuple(value.get("aliases", ()))
        names = (value["common_name"], value["scientific_name"], *aliases)
        if len({normalize_name(item) for item in names}) != len(names):
            raise CatalogIntegrityError(f"duplicate names in species {species_id}")
        entry_source_ids = _string_tuple(value.get("source_ids", ()))
        if not entry_source_ids or not set(entry_source_ids).issubset(source_ids):
            raise CatalogIntegrityError(f"species {species_id} references an unknown source")
        image_source_ids = _string_tuple(value.get("image_source_ids", ()))
        if not set(image_source_ids).issubset(source_ids):
            raise CatalogIntegrityError(f"species {species_id} references an unknown image source")
        raw_assessments = value.get("assessments", ())
        if not isinstance(raw_assessments, (list, tuple)):
            raise CatalogIntegrityError(f"assessments for {species_id} must be an array")
        assessments = tuple(
            ConservationAssessment(
                authority=str(item.get("authority") or "").strip(),
                status=str(item.get("status") or "").strip(),
                assessment_url=_optional_string(item.get("assessment_url")),
                assessed_at=_optional_string(item.get("assessed_at")),
                notes=_optional_string(item.get("notes")),
            )
            for item in raw_assessments
            if isinstance(item, Mapping)
        )
        if len(assessments) != len(raw_assessments):
            raise CatalogIntegrityError(f"assessments for {species_id} must contain objects")
        if any(not item.authority or not item.status for item in assessments):
            raise CatalogIntegrityError(f"invalid conservation assessment for {species_id}")
        if len({item.authority for item in assessments}) != len(assessments):
            raise CatalogIntegrityError(f"duplicate conservation authority for {species_id}")
        knowledge: list[KnowledgeSeed] = []
        raw_knowledge = value.get("knowledge", ())
        if not isinstance(raw_knowledge, (list, tuple)):
            raise CatalogIntegrityError(f"knowledge for {species_id} must be an array")
        for item in raw_knowledge:
            if not isinstance(item, Mapping):
                raise CatalogIntegrityError(f"invalid knowledge entry for {species_id}")
            text = str(item.get("text") or "").strip()
            source_id = str(item.get("source_id") or "").strip()
            if not text or source_id not in source_ids:
                raise CatalogIntegrityError(f"invalid knowledge source for {species_id}")
            knowledge.append(KnowledgeSeed(text, source_id, str(item.get("kind") or "fact")))
        if not knowledge:
            raise CatalogIntegrityError(f"species {species_id} needs at least one sourced fact")
        return cls(
            species_id=species_id,
            scientific_name=value["scientific_name"].strip(),
            common_name=value["common_name"].strip(),
            family=value["family"].strip(),
            region=value["region"].strip(),
            category=value["category"].strip(),
            native_status=value["native_status"].strip(),
            is_native=_strict_bool(value.get("is_native", False), "is_native"),
            conservation_status=value["conservation_status"].strip(),
            ecology=value["ecology"].strip(),
            short_notes=value["short_notes"].strip(),
            aliases=aliases,
            image_views=_string_tuple(value.get("image_views", ())),
            image_source_ids=image_source_ids,
            source_ids=entry_source_ids,
            assessments=assessments,
            knowledge=tuple(knowledge),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "species_id": self.species_id,
            "scientific_name": self.scientific_name,
            "common_name": self.common_name,
            "family": self.family,
            "region": self.region,
            "category": self.category,
            "native_status": self.native_status,
            "is_native": self.is_native,
            "conservation_status": self.conservation_status,
            "ecology": self.ecology,
            "short_notes": self.short_notes,
            "aliases": list(self.aliases),
            "image_views": list(self.image_views),
            "image_source_ids": list(self.image_source_ids),
            "source_ids": list(self.source_ids),
            "assessments": [
                {
                    "authority": item.authority,
                    "status": item.status,
                    "assessment_url": item.assessment_url,
                    "assessed_at": item.assessed_at,
                    "notes": item.notes,
                }
                for item in self.assessments
            ],
            "knowledge": [
                {"text": item.text, "source_id": item.source_id, "kind": item.kind}
                for item in self.knowledge
            ],
        }


@dataclass(frozen=True, slots=True)
class ModelReleaseSeed:
    release_id: str
    model_id: str
    version: str
    artifact_path: str
    artifact_sha256: str
    runtime: str
    label_map: Mapping[str, str]
    preprocessing: Mapping[str, Any]
    metrics: Mapping[str, Any]
    calibration: Mapping[str, Any]
    dataset_provenance: Mapping[str, Any]
    supported_region: str
    active: bool


@dataclass(frozen=True, slots=True)
class CatalogDefinition:
    catalog_id: str
    version: str
    region: str
    sources: tuple[SourceRecord, ...]
    species: tuple[SpeciesRecord, ...]
    model_release: ModelReleaseSeed
    digest: str
    label_map: Mapping[str, str]

    def species_by_id(self) -> Mapping[str, SpeciesRecord]:
        return MappingProxyType({item.species_id: item for item in self.species})


def load_catalog(path: Path) -> CatalogDefinition:
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogIntegrityError(f"could not read catalog {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise CatalogIntegrityError("catalog root must be an object")
    catalog_id = _required_root_string(raw, "catalog_id")
    version = _required_root_string(raw, "version")
    region = _required_root_string(raw, "region")
    sources = tuple(SourceRecord.from_dict(item) for item in raw.get("sources", ()))
    if len({item.source_id for item in sources}) != len(sources):
        raise CatalogIntegrityError("source IDs must be unique")
    source_ids = {item.source_id for item in sources}
    species = tuple(SpeciesRecord.from_dict(item, source_ids) for item in raw.get("species", ()))
    if len(species) < 7:
        raise CatalogIntegrityError("Phase 6 requires at least seven species")
    if len({item.species_id for item in species}) != len(species):
        raise CatalogIntegrityError("species IDs must be unique and stable")
    all_names: dict[str, str] = {}
    for item in species:
        for name in (item.common_name, item.scientific_name, *item.aliases):
            normalized = normalize_name(name)
            previous = all_names.get(normalized)
            if previous is not None and previous != item.species_id:
                raise CatalogIntegrityError(f"ambiguous catalog name: {name}")
            all_names[normalized] = item.species_id

    model_raw = raw.get("model_release")
    if not isinstance(model_raw, dict):
        raise CatalogIntegrityError("catalog requires model_release metadata")
    raw_labels = model_raw.get("label_map")
    if not isinstance(raw_labels, dict) or not raw_labels:
        raise CatalogIntegrityError("model release requires a label map")
    label_map = {str(key): str(value) for key, value in raw_labels.items()}
    if len(label_map) != len(species) or set(label_map.values()) != {item.species_id for item in species}:
        raise CatalogIntegrityError("model label map must cover every catalog species exactly once")
    try:
        label_numbers = sorted(int(key) for key in label_map)
    except (TypeError, ValueError) as exc:
        raise CatalogIntegrityError("model label map keys must be integer class indices") from exc
    if label_numbers != list(range(len(species))):
        raise CatalogIntegrityError("model label map class indices must be contiguous from zero")
    release = ModelReleaseSeed(
        release_id=_required_mapping_string(model_raw, "release_id"),
        model_id=_required_mapping_string(model_raw, "model_id"),
        version=_required_mapping_string(model_raw, "version"),
        artifact_path=_required_mapping_string(model_raw, "artifact_path"),
        artifact_sha256=_required_mapping_string(model_raw, "artifact_sha256"),
        runtime=_required_mapping_string(model_raw, "runtime"),
        label_map=MappingProxyType(dict(label_map)),
        preprocessing=_mapping(model_raw.get("preprocessing")),
        metrics=_mapping(model_raw.get("metrics")),
        calibration=_mapping(model_raw.get("calibration")),
        dataset_provenance=_mapping(model_raw.get("dataset_provenance")),
        supported_region=_required_mapping_string(model_raw, "supported_region"),
        active=bool(model_raw.get("active", True)),
    )
    if not re.fullmatch(r"[0-9a-f]{64}", release.artifact_sha256):
        raise CatalogIntegrityError("model release artifact_sha256 must be a lowercase SHA-256")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    return CatalogDefinition(
        catalog_id=catalog_id,
        version=version,
        region=region,
        sources=sources,
        species=species,
        model_release=release,
        digest=digest,
        label_map=MappingProxyType(dict(label_map)),
    )


def _required_root_string(raw: Mapping[str, Any], key: str) -> str:
    return _required_mapping_string(raw, key)


def _required_mapping_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CatalogIntegrityError(f"catalog metadata {key!r} must be non-empty")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CatalogIntegrityError("optional catalog strings must be non-empty strings")
    return value.strip()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise CatalogIntegrityError("catalog string lists must be arrays")
    result = tuple(item.strip() for item in value if isinstance(item, str) and item.strip())
    if len(result) != len(value):
        raise CatalogIntegrityError("catalog string lists may not contain empty values")
    return result


def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, dict):
        raise CatalogIntegrityError("model metadata fields must be objects")
    return MappingProxyType(dict(value))


def _strict_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogIntegrityError(f"catalog field {field_name!r} must be boolean")
    return value
