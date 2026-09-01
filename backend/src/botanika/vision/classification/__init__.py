"""Species classifier contract, Phase 4 stub, and crop pipeline."""

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

__all__ = [
    "CancellationToken",
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
    "STUB_CLASSIFIER_VERSION",
    "SpeciesClassifier",
    "SpeciesSuggestion",
    "format_diagnostic",
]
