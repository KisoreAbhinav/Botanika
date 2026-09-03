"""Species classifier contract, Phase 6 compact model, and crop pipeline."""

from .classifier import (
    DEMO_DATA_LABEL,
    STUB_CLASSIFIER_VERSION,
    CancellationToken,
    ClassificationResult,
    ClassificationStatus,
    ClassifierError,
    ClassifierInput,
    DummyClassifier,
    DummyScenario,
    MalformedImageError,
    SpeciesClassifier,
    SpeciesSuggestion,
)
from .pipeline import ClassificationPipeline, ClassificationRun, format_diagnostic
from .compact import (
    CatalogFeatureClassifier,
    CompactSpeciesClassifier,
    ModelMetadata,
    RealSpeciesClassifier,
    UnavailableSpeciesClassifier,
    extract_features,
)

__all__ = [
    "CancellationToken",
    "CatalogFeatureClassifier",
    "CompactSpeciesClassifier",
    "ClassificationPipeline",
    "ClassificationResult",
    "ClassificationRun",
    "ClassificationStatus",
    "ClassifierError",
    "ClassifierInput",
    "DEMO_DATA_LABEL",
    "DummyClassifier",
    "DummyScenario",
    "MalformedImageError",
    "ModelMetadata",
    "RealSpeciesClassifier",
    "STUB_CLASSIFIER_VERSION",
    "SpeciesClassifier",
    "SpeciesSuggestion",
    "UnavailableSpeciesClassifier",
    "extract_features",
    "format_diagnostic",
]
