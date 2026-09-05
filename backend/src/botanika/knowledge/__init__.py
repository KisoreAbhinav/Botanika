"""Offline, provenance-first botanical catalog and retrieval services."""

from .catalog import (
    CatalogDefinition,
    CatalogIntegrityError,
    ConservationAssessment,
    KnowledgeSeed,
    ModelReleaseSeed,
    SourceRecord,
    SpeciesRecord,
    load_catalog,
    normalize_name,
)
from .store import ABSTENTION, GroundedAnswer, KnowledgeHit, KnowledgeStore, SpeciesCatalog
from .regional import (
    REGIONAL_CATEGORIES,
    CampusCatalogView,
    ReferenceCatalog,
    RegionalCatalogError,
    load_reference_catalog,
    load_regional_catalog,
    merge_catalog_views,
)

__all__ = [
    "ABSTENTION",
    "CatalogDefinition",
    "CatalogIntegrityError",
    "ConservationAssessment",
    "GroundedAnswer",
    "KnowledgeHit",
    "KnowledgeSeed",
    "KnowledgeStore",
    "ModelReleaseSeed",
    "SourceRecord",
    "SpeciesCatalog",
    "SpeciesRecord",
    "load_catalog",
    "normalize_name",
    "REGIONAL_CATEGORIES",
    "CampusCatalogView",
    "ReferenceCatalog",
    "RegionalCatalogError",
    "load_reference_catalog",
    "load_regional_catalog",
    "merge_catalog_views",
]
