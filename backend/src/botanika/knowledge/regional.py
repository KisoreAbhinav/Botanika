"""Sourced regional flora checklist used by the discovery library.

The classifier catalog is intentionally small and model-gated.  The regional
checklist is a separate, read-only reference set: it can be larger than the
classes available to the Pi classifier without implying that every checklist
plant can be identified offline.  Records are kept as plain dictionaries so a
catalog revision does not require a database migration.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


class RegionalCatalogError(ValueError):
    """Raised when the regional checklist is malformed or under-sourced."""


REGIONAL_CATEGORIES = (
    "Indian native",
    "Cultivated / naturalized",
    "Ornamental / cultivated",
    "Invasive / introduced",
)


def load_regional_catalog(path: Path) -> dict[str, Any]:
    """Load and validate the immutable regional checklist JSON.

    Validation is deliberately strict for identity and provenance, while the
    facts themselves remain descriptive text supplied by the reviewed source.
    The loader returns JSON-compatible values and adds a deterministic digest.
    """

    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegionalCatalogError(f"could not read regional catalog {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegionalCatalogError("regional catalog root must be an object")
    for key in ("catalog_id", "version", "region", "scope_note", "sources", "species"):
        if not isinstance(raw.get(key), str if key in {"catalog_id", "version", "region", "scope_note"} else list):
            raise RegionalCatalogError(f"regional catalog field {key!r} has an invalid type")
        if key in {"catalog_id", "version", "region", "scope_note"} and not raw[key].strip():
            raise RegionalCatalogError(f"regional catalog field {key!r} must be non-empty")
    occurrence_basis = raw.get("occurrence_basis", {})
    if not isinstance(occurrence_basis, Mapping):
        raise RegionalCatalogError("regional catalog occurrence_basis must be an object")
    source_rows = raw["sources"]
    sources: dict[str, dict[str, Any]] = {}
    for source in source_rows:
        if not isinstance(source, Mapping):
            raise RegionalCatalogError("regional catalog sources must be objects")
        required = ("source_id", "title", "publisher", "url", "license", "license_url")
        if any(not isinstance(source.get(key), str) or not str(source[key]).strip() for key in required):
            raise RegionalCatalogError("regional catalog sources require URL and license metadata")
        source_id = str(source["source_id"]).strip()
        if source_id in sources:
            raise RegionalCatalogError(f"duplicate regional source ID: {source_id}")
        if not str(source["url"]).startswith(("https://", "http://")):
            raise RegionalCatalogError(f"regional source URL must be absolute: {source_id}")
        source_value = dict(source)
        source_value["source_id"] = source_id
        sources[source_id] = source_value

    species_rows = raw["species"]
    if len(species_rows) < 12:
        raise RegionalCatalogError("regional checklist must contain materially more than the demo set")
    seen_ids: set[str] = set()
    seen_names: dict[str, str] = {}
    species: list[dict[str, Any]] = []
    for item in species_rows:
        if not isinstance(item, Mapping):
            raise RegionalCatalogError("regional species entries must be objects")
        required = (
            "species_id", "scientific_name", "common_name", "family", "category",
            "native_status", "conservation_status", "ecology", "short_notes", "source_ids",
        )
        if any(not isinstance(item.get(key), str) or not str(item[key]).strip() for key in required[:-1]):
            raise RegionalCatalogError("regional species entries require complete botanical metadata")
        species_id = str(item["species_id"]).strip()
        if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]+", species_id):
            raise RegionalCatalogError(f"invalid regional species ID: {species_id!r}")
        if species_id in seen_ids:
            raise RegionalCatalogError(f"duplicate regional species ID: {species_id}")
        seen_ids.add(species_id)
        category = str(item["category"]).strip()
        if category not in REGIONAL_CATEGORIES:
            raise RegionalCatalogError(f"unsupported regional category: {category}")
        source_ids = item.get("source_ids")
        if not isinstance(source_ids, list) or not source_ids or any(
            not isinstance(value, str) or value.strip() not in sources for value in source_ids
        ):
            raise RegionalCatalogError(f"regional species {species_id} must reference known sources")
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list):
            raise RegionalCatalogError(f"regional species {species_id} has invalid aliases")
        names = [str(item["scientific_name"]), str(item["common_name"]), *aliases]
        if not all(isinstance(name, str) and name.strip() for name in names):
            raise RegionalCatalogError(f"regional species {species_id} has invalid aliases")
        for name in names:
            normalized = _normalize(name)
            previous = seen_names.get(normalized)
            if previous is not None and previous != species_id:
                raise RegionalCatalogError(f"ambiguous regional name: {name}")
            seen_names[normalized] = species_id
        knowledge = item.get("knowledge")
        if not isinstance(knowledge, list) or not knowledge:
            raise RegionalCatalogError(f"regional species {species_id} needs sourced facts")
        normalized_knowledge: list[dict[str, str]] = []
        for fact in knowledge:
            if not isinstance(fact, Mapping):
                raise RegionalCatalogError(f"invalid regional knowledge for {species_id}")
            text = str(fact.get("text") or "").strip()
            source_id = str(fact.get("source_id") or "").strip()
            if not text or source_id not in sources:
                raise RegionalCatalogError(f"regional fact for {species_id} references an unknown source")
            normalized_knowledge.append({
                "text": text,
                "source_id": source_id,
                "kind": str(fact.get("kind") or "fact").strip() or "fact",
            })
        value = dict(item)
        value["species_id"] = species_id
        value["source_ids"] = [str(value).strip() for value in source_ids]
        value["aliases"] = [str(value).strip() for value in aliases]
        value["knowledge"] = normalized_knowledge
        value["is_native"] = bool(item.get("is_native", False))
        value["status"] = "found" if item.get("status") == "found" else "not_found"
        species.append(value)

    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return {
        "catalog_id": str(raw["catalog_id"]).strip(),
        "version": str(raw["version"]).strip(),
        "region": str(raw["region"]).strip(),
        "scope_note": str(raw["scope_note"]).strip(),
        "occurrence_basis": dict(occurrence_basis),
        "sources": list(sources.values()),
        "species": species,
        "digest": hashlib.sha256(canonical).hexdigest(),
    }


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", value.lower()).split())


__all__ = ["REGIONAL_CATEGORIES", "RegionalCatalogError", "load_regional_catalog"]
