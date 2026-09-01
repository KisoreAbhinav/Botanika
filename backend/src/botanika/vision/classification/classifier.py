"""Species-classification contracts and the deterministic Phase 4 stub.

The classifier boundary intentionally accepts either a crop path or an image
object.  The real model can replace :class:`DummyClassifier` without changing
the capture pipeline or its result schema.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol, TypeAlias

import cv2
import numpy as np


ClassifierInput: TypeAlias = Path | str | np.ndarray | None
DEMO_DATA_LABEL = "DEMO DATA"
STUB_CLASSIFIER_VERSION = "stub-phase-4"


class ClassificationStatus(str, Enum):
    """Terminal outcome of one classifier request."""

    ACCEPTED = "accepted"
    UNCERTAIN = "uncertain"
    ERROR = "error"
    CANCELLED = "cancelled"
    MALFORMED_IMAGE = "malformed_image"


class DummyScenario(str, Enum):
    """Deterministic response modes used to exercise Phase 4 failure paths."""

    ACCEPTED = "accepted"
    UNCERTAIN = "uncertain"
    ERROR = "error"
    CANCELLED = "cancelled"


class ClassifierError(RuntimeError):
    """Base error for classifier input and inference failures."""


class MalformedImageError(ClassifierError):
    """Raised internally when a crop cannot be decoded or validated."""


class CancellationToken:
    """Small cooperative cancellation token for bounded local inference."""

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True


@dataclass(frozen=True, slots=True)
class SpeciesSuggestion:
    """A non-authoritative suggestion shown only for an uncertain result."""

    common_name: str
    scientific_name: str
    confidence: float

    def __post_init__(self) -> None:
        if not self.common_name.strip() or not self.scientific_name.strip():
            raise ValueError("species suggestions require names")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("suggestion confidence must be between 0 and 1")

    def to_dict(self) -> dict[str, object]:
        return {
            "common_name": self.common_name,
            "scientific_name": self.scientific_name,
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Stable classifier output shared by the stub and future real models."""

    status: ClassificationStatus
    species_id: str | None = None
    common_name: str | None = None
    scientific_name: str | None = None
    family: str | None = None
    category: str | None = None
    conservation_status: str | None = None
    confidence: float | None = None
    short_notes: str | None = None
    sources: tuple[str, ...] = ()
    classifier_version: str = ""
    is_stub: bool = False
    demo_label: str = ""
    suggestions: tuple[SpeciesSuggestion, ...] = ()
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ClassificationStatus):
            object.__setattr__(self, "status", ClassificationStatus(self.status))
        if not self.classifier_version.strip():
            raise ValueError("classifier_version must not be empty")
        if not isinstance(self.is_stub, bool):
            raise ValueError("is_stub must be a boolean")
        if self.is_stub and self.demo_label != DEMO_DATA_LABEL:
            raise ValueError("stub responses must be labelled DEMO DATA")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

        if self.status is ClassificationStatus.ACCEPTED:
            required = (
                self.species_id,
                self.common_name,
                self.scientific_name,
                self.family,
                self.category,
                self.conservation_status,
                self.short_notes,
            )
            if any(value is None or not str(value).strip() for value in required):
                raise ValueError("accepted results require complete species details")
            if self.confidence is None or not self.sources:
                raise ValueError("accepted results require confidence and sources")
            if self.error is not None:
                raise ValueError("accepted results cannot contain an error")
        elif self.status is ClassificationStatus.UNCERTAIN:
            if self.confidence is None:
                raise ValueError("uncertain results require confidence")
            if any(
                value is not None
                for value in (
                    self.species_id,
                    self.common_name,
                    self.scientific_name,
                    self.family,
                    self.category,
                    self.conservation_status,
                )
            ):
                raise ValueError("uncertain results must not force a species identity")
        else:
            if not self.error or not self.error.strip():
                raise ValueError("failed results require an error message")

    @property
    def is_accepted(self) -> bool:
        return self.status is ClassificationStatus.ACCEPTED

    @property
    def display_label(self) -> str:
        """Human-facing status that cannot hide the demo nature of the result."""

        prefix = f"{self.demo_label}: " if self.demo_label else ""
        if self.status is ClassificationStatus.ACCEPTED:
            return f"{prefix}{self.common_name}"
        if self.status is ClassificationStatus.UNCERTAIN:
            return f"{prefix}Not confident"
        if self.status is ClassificationStatus.MALFORMED_IMAGE:
            return f"{prefix}Malformed image"
        if self.status is ClassificationStatus.CANCELLED:
            return f"{prefix}Classification cancelled"
        return f"{prefix}Classifier error"

    def __str__(self) -> str:
        """Keep the provenance warning visible in ordinary logs and displays."""

        return f"{self.display_label} [{self.classifier_version}]"

    def to_dict(self) -> dict[str, object]:
        """Serialize the contract without losing the stub warning."""

        return {
            "status": self.status.value,
            "species_id": self.species_id,
            "common_name": self.common_name,
            "scientific_name": self.scientific_name,
            "family": self.family,
            "category": self.category,
            "conservation_status": self.conservation_status,
            "confidence": self.confidence,
            "short_notes": self.short_notes,
            "sources": list(self.sources),
            "classifier_version": self.classifier_version,
            "is_stub": self.is_stub,
            "demo_label": self.demo_label,
            "suggestions": [suggestion.to_dict() for suggestion in self.suggestions],
            "error": self.error,
        }


class SpeciesClassifier(Protocol):
    """Interface implemented by the Phase 4 stub and future species models."""

    classifier_version: str
    is_stub: bool

    def classify(
        self,
        crop: ClassifierInput,
        *,
        cancellation: CancellationToken | None = None,
    ) -> ClassificationResult: ...


class DummyClassifier:
    """Return deterministic, explicitly fake species data for pipeline proof."""

    classifier_version = STUB_CLASSIFIER_VERSION
    is_stub = True

    def __init__(
        self,
        *,
        scenario: DummyScenario = DummyScenario.ACCEPTED,
        confidence: float = 0.93,
        acceptance_threshold: float = 0.75,
    ) -> None:
        if not isinstance(scenario, DummyScenario):
            scenario = DummyScenario(scenario)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not 0.0 <= acceptance_threshold <= 1.0:
            raise ValueError("acceptance_threshold must be between 0 and 1")
        self.scenario = scenario
        self.confidence = confidence
        self.acceptance_threshold = acceptance_threshold

    def classify(
        self,
        crop: ClassifierInput,
        *,
        cancellation: CancellationToken | None = None,
    ) -> ClassificationResult:
        """Validate one crop and return a deterministic schema-valid response."""

        if _cancelled(cancellation) or self.scenario is DummyScenario.CANCELLED:
            return self._failure(
                ClassificationStatus.CANCELLED,
                "Classification cancelled before inference",
            )

        try:
            _load_crop(crop)
        except MalformedImageError as exc:
            return self._failure(ClassificationStatus.MALFORMED_IMAGE, str(exc))

        if _cancelled(cancellation):
            return self._failure(
                ClassificationStatus.CANCELLED,
                "Classification cancelled before inference",
            )
        if self.scenario is DummyScenario.ERROR:
            return self._failure(
                ClassificationStatus.ERROR,
                "Deterministic Phase 4 classifier error",
            )

        if self.scenario is DummyScenario.UNCERTAIN or self.confidence < self.acceptance_threshold:
            return ClassificationResult(
                status=ClassificationStatus.UNCERTAIN,
                confidence=min(self.confidence, 0.49),
                short_notes="Demo suggestion only; request another view before accepting.",
                sources=("DEMO DATA: phase-4 fixture",),
                classifier_version=self.classifier_version,
                is_stub=True,
                demo_label=DEMO_DATA_LABEL,
                suggestions=(
                    SpeciesSuggestion(
                        common_name="Demo Plant",
                        scientific_name="Specimenus demonstratus",
                        confidence=min(self.confidence, 0.49),
                    ),
                ),
            )

        return ClassificationResult(
            status=ClassificationStatus.ACCEPTED,
            species_id="demo:phase4:example-plant",
            common_name="Demo Plant",
            scientific_name="Specimenus demonstratus",
            family="Demonstration family",
            category="Demo specimen",
            conservation_status="Demo only — not assessed",
            confidence=self.confidence,
            short_notes="Placeholder output proving crop-to-result wiring; not a botanical identification.",
            sources=("DEMO DATA: phase-4 fixture",),
            classifier_version=self.classifier_version,
            is_stub=True,
            demo_label=DEMO_DATA_LABEL,
        )

    def _failure(self, status: ClassificationStatus, error: str) -> ClassificationResult:
        return ClassificationResult(
            status=status,
            short_notes="No species identity was produced.",
            sources=("DEMO DATA: phase-4 fixture",),
            classifier_version=self.classifier_version,
            is_stub=True,
            demo_label=DEMO_DATA_LABEL,
            error=error,
        )


def _cancelled(token: CancellationToken | None) -> bool:
    return token is not None and token.is_cancelled


def _load_crop(crop: ClassifierInput) -> np.ndarray:
    """Decode and validate a BGR crop without writing or retaining it."""

    if isinstance(crop, (str, Path)):
        path = Path(crop)
        if not path.is_file():
            raise MalformedImageError(f"crop path does not exist: {path}")
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise MalformedImageError(f"crop could not be decoded: {path}")
    elif isinstance(crop, np.ndarray):
        image = crop
    else:
        raise MalformedImageError(
            f"expected a crop path or 3-channel image object, got {type(crop).__name__}"
        )

    if image.ndim != 3 or image.shape[2] != 3 or image.shape[0] <= 0 or image.shape[1] <= 0:
        raise MalformedImageError(
            f"expected a non-empty 3-channel BGR crop, got {getattr(image, 'shape', None)!r}"
        )
    return image
