"""Accepted-crop to classifier orchestration and diagnostic association."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

import numpy as np

from ..quality.capture import CaptureResult
from .classifier import (
    ClassificationResult,
    ClassificationStatus,
    ClassifierInput,
    CancellationToken,
    DEMO_DATA_LABEL,
    SpeciesClassifier,
)


@dataclass(frozen=True, slots=True)
class ClassificationRun:
    """One classifier response associated with exactly one Phase 3 crop."""

    request_id: str
    crop_path: Path | None
    crop_hash: str
    capture: CaptureResult
    started_at: float
    completed_at: float
    duration_ms: float
    result: ClassificationResult

    @property
    def status(self) -> ClassificationStatus:
        return self.result.status

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "crop_path": str(self.crop_path) if self.crop_path is not None else None,
            "crop_hash": self.crop_hash,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": self.duration_ms,
            "result": self.result.to_dict(),
        }


class ClassificationPipeline:
    """Run the classifier once for a successful accepted crop."""

    def __init__(
        self,
        classifier: SpeciesClassifier,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.classifier = classifier
        self._clock = clock
        self._sequence = 0

    def classify_capture(
        self,
        capture: CaptureResult,
        *,
        image: np.ndarray | None = None,
        cancellation: CancellationToken | None = None,
        request_id: str | None = None,
    ) -> ClassificationRun:
        """Pass the crop path directly to the classifier and retain its linkage."""

        if not isinstance(capture, CaptureResult):
            raise TypeError("capture must be a CaptureResult")
        self._sequence += 1
        run_id = request_id or f"classification-{self._sequence:06d}"
        started_at = self._clock()
        crop: ClassifierInput = capture.path if capture.path is not None else image
        try:
            result = self.classifier.classify(crop, cancellation=cancellation)
            if not isinstance(result, ClassificationResult):
                raise TypeError("classifier returned an invalid result object")
        except Exception as exc:
            result = _classifier_error(self.classifier, str(exc))
        completed_at = self._clock()
        return ClassificationRun(
            request_id=run_id,
            crop_path=capture.path,
            crop_hash=capture.content_hash,
            capture=capture,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(0.0, (completed_at - started_at) * 1000.0),
            result=result,
        )


def format_diagnostic(run: ClassificationRun) -> str:
    """Format a compact local diagnostic with an unavoidable demo warning."""

    result = run.result
    label = result.demo_label if result.is_stub else "PRODUCTION MODEL"
    lines = [
        f"[{label}] {result.display_label} | status={result.status.value}",
        f"request={run.request_id} crop={run.crop_path} hash={run.crop_hash[:12]} "
        f"duration={run.duration_ms:.1f}ms version={result.classifier_version}",
    ]
    if result.is_accepted:
        lines.append(
            f"confidence={result.confidence:.0%} scientific={result.scientific_name} "
            f"family={result.family} category={result.category} "
            f"conservation={result.conservation_status}"
        )
    elif result.status is ClassificationStatus.UNCERTAIN:
        suggestions = ", ".join(
            f"{item.common_name} ({item.confidence:.0%})" for item in result.suggestions
        ) or "none"
        lines.append(f"confidence={result.confidence:.0%} suggestions={suggestions}")
    else:
        lines.append(f"error={result.error}")
    return "\n".join(lines)


def _classifier_error(classifier: SpeciesClassifier, message: str) -> ClassificationResult:
    is_stub = bool(getattr(classifier, "is_stub", False))
    version = str(getattr(classifier, "classifier_version", "unknown"))
    return ClassificationResult(
        status=ClassificationStatus.ERROR,
        short_notes="No species identity was produced.",
        sources=((f"{DEMO_DATA_LABEL}: classifier boundary",) if is_stub else ()),
        classifier_version=version,
        is_stub=is_stub,
        demo_label=DEMO_DATA_LABEL if is_stub else "",
        error=f"Classifier invocation failed: {message}",
    )
