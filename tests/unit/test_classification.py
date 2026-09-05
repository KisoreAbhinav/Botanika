from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from botanika.vision.classification import (
    CancellationToken,
    ClassificationPipeline,
    ClassificationResult,
    ClassificationStatus,
    DummyClassifier,
    DummyScenario,
    STUB_CLASSIFIER_VERSION,
    format_diagnostic,
)
from botanika.vision.detection import BoundingBox
from botanika.vision.quality import CaptureResult


def capture(path: Path | None, content_hash: str = "a" * 64) -> CaptureResult:
    return CaptureResult(
        path=path,
        crop_box=BoundingBox(2, 3, 42, 43),
        width=40,
        height=40,
        content_hash=content_hash,
    )


def valid_image() -> np.ndarray:
    image = np.zeros((48, 48, 3), dtype=np.uint8)
    image[::2, ::2] = (40, 120, 220)
    image[1::2, 1::2] = (220, 120, 40)
    return image


class RecordingClassifier:
    classifier_version = "recording-test-1"
    is_stub = False

    def __init__(self) -> None:
        self.received = None

    def classify(self, crop, *, cancellation=None):
        self.received = crop
        return ClassificationResult(
            status=ClassificationStatus.ACCEPTED,
            species_id="test:species",
            common_name="Test Plant",
            scientific_name="Testus plantus",
            family="Test family",
            category="Test category",
            conservation_status="Not assessed",
            confidence=0.8,
            short_notes="Test result.",
            sources=("test://source",),
            classifier_version=self.classifier_version,
        )


class ClassificationTests(unittest.TestCase):
    def test_dummy_classifier_is_deterministic_and_schema_complete(self):
        image = valid_image()
        first = DummyClassifier().classify(image)
        second = DummyClassifier().classify(image.copy())

        self.assertEqual(first, second)
        self.assertEqual(first.status, ClassificationStatus.ACCEPTED)
        self.assertEqual(first.species_id, "demo:phase4:example-plant")
        self.assertEqual(first.classifier_version, STUB_CLASSIFIER_VERSION)
        self.assertTrue(first.is_stub)
        self.assertEqual(first.demo_label, "DEMO DATA")
        self.assertIn("DEMO DATA", str(first))
        self.assertEqual(first.to_dict()["is_stub"], True)

    def test_pipeline_passes_crop_path_directly_and_preserves_association(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "crop.png"
            self.assertTrue(cv2.imwrite(str(path), valid_image()))
            expected_capture = capture(path, "b" * 64)
            classifier = RecordingClassifier()
            clock_values = iter((10.0, 10.125))
            pipeline = ClassificationPipeline(classifier, clock=lambda: next(clock_values))

            run = pipeline.classify_capture(expected_capture, request_id="scan-42")

            self.assertIs(classifier.received, path)
            self.assertEqual(run.request_id, "scan-42")
            self.assertEqual(run.crop_path, path)
            self.assertEqual(run.crop_hash, "b" * 64)
            self.assertIs(run.capture, expected_capture)
            self.assertEqual(run.duration_ms, 125.0)
            self.assertTrue(run.result.is_accepted)

    def test_uncertain_stub_abstains_and_exposes_suggestions(self):
        result = DummyClassifier(scenario=DummyScenario.UNCERTAIN).classify(valid_image())

        self.assertEqual(result.status, ClassificationStatus.UNCERTAIN)
        self.assertIsNone(result.species_id)
        self.assertTrue(result.suggestions)
        self.assertLess(result.confidence, 0.75)
        self.assertEqual(result.display_label, "DEMO DATA: Not confident")

    def test_validation_pending_label_is_distinct_from_low_confidence(self):
        result = ClassificationResult(
            status=ClassificationStatus.UNCERTAIN,
            confidence=0.94,
            short_notes="The provisional index matched this view.",
            classifier_version="test-1",
            validation_pending=True,
        )

        self.assertEqual(result.display_label, "Validation pending")
        self.assertTrue(result.to_dict()["validation_pending"])
        self.assertEqual(
            ClassificationResult(
                status=ClassificationStatus.UNCERTAIN,
                confidence=0.40,
                short_notes="The view is ambiguous.",
                classifier_version="test-1",
            ).display_label,
            "Not confident",
        )

    def test_low_confidence_path_preserves_the_configured_confidence(self):
        result = DummyClassifier(
            confidence=0.74,
            acceptance_threshold=0.75,
        ).classify(valid_image())

        self.assertEqual(result.status, ClassificationStatus.UNCERTAIN)
        self.assertEqual(result.confidence, 0.74)
        self.assertEqual(result.suggestions[0].confidence, 0.74)

    def test_error_and_cancellation_stub_paths_are_explicit(self):
        error = DummyClassifier(scenario=DummyScenario.ERROR).classify(valid_image())
        token = CancellationToken()
        token.cancel()
        cancelled = DummyClassifier().classify(valid_image(), cancellation=token)

        self.assertEqual(error.status, ClassificationStatus.ERROR)
        self.assertIn("deterministic", error.error.lower())
        self.assertEqual(cancelled.status, ClassificationStatus.CANCELLED)
        self.assertTrue(error.is_stub)
        self.assertTrue(cancelled.is_stub)
        self.assertIn("DEMO DATA", format_diagnostic(
            ClassificationPipeline(DummyClassifier()).classify_capture(
                capture(None), image=valid_image(), cancellation=token
            )
        ))

    def test_malformed_image_returns_a_schema_valid_failure(self):
        malformed = DummyClassifier().classify(np.zeros((10, 10), dtype=np.uint8))
        missing = DummyClassifier().classify(Path("/tmp/does-not-exist-botanika-crop.png"))
        nan_pixels = DummyClassifier().classify(
            np.full((10, 10, 3), np.nan, dtype=np.float32)
        )
        object_pixels = DummyClassifier().classify(
            np.full((10, 10, 3), "not pixels", dtype=object)
        )

        self.assertEqual(malformed.status, ClassificationStatus.MALFORMED_IMAGE)
        self.assertEqual(missing.status, ClassificationStatus.MALFORMED_IMAGE)
        self.assertEqual(nan_pixels.status, ClassificationStatus.MALFORMED_IMAGE)
        self.assertEqual(object_pixels.status, ClassificationStatus.MALFORMED_IMAGE)
        self.assertTrue(malformed.error)
        self.assertEqual(malformed.classifier_version, STUB_CLASSIFIER_VERSION)

    def test_result_schema_rejects_contradictory_or_empty_fields(self):
        accepted_fields = {
            "status": ClassificationStatus.ACCEPTED,
            "species_id": "test:species",
            "common_name": "Test Plant",
            "scientific_name": "Testus plantus",
            "family": "Test family",
            "category": "Test category",
            "conservation_status": "Not assessed",
            "confidence": 0.8,
            "short_notes": "Test result.",
            "sources": ("test://source",),
            "classifier_version": "test-1",
        }

        with self.assertRaisesRegex(ValueError, "non-empty strings"):
            ClassificationResult(**{**accepted_fields, "sources": ("",)})
        with self.assertRaisesRegex(ValueError, "must not contain a species identity"):
            ClassificationResult(
                status=ClassificationStatus.ERROR,
                species_id="test:should-not-exist",
                classifier_version="test-1",
                error="fixture error",
            )
        with self.assertRaisesRegex(ValueError, "must not carry a demo label"):
            ClassificationResult(
                **{**accepted_fields, "demo_label": "DEMO DATA"}
            )

    def test_pipeline_converts_unexpected_classifier_exception_to_error_result(self):
        class BrokenClassifier:
            classifier_version = "broken-test-1"
            is_stub = True

            def classify(self, crop, *, cancellation=None):
                raise RuntimeError("fixture failure")

        run = ClassificationPipeline(BrokenClassifier()).classify_capture(
            capture(None), image=valid_image()
        )

        self.assertEqual(run.status, ClassificationStatus.ERROR)
        self.assertIn("fixture failure", run.result.error)
        self.assertTrue(run.result.is_stub)
        self.assertEqual(run.result.demo_label, "DEMO DATA")

    def test_pipeline_fails_closed_when_stub_result_hides_demo_provenance(self):
        class MislabelledStub:
            classifier_version = STUB_CLASSIFIER_VERSION
            is_stub = True

            def classify(self, crop, *, cancellation=None):
                return ClassificationResult(
                    status=ClassificationStatus.ACCEPTED,
                    species_id="demo:hidden",
                    common_name="Hidden Demo",
                    scientific_name="Fakus plantus",
                    family="Fake family",
                    category="Fake category",
                    conservation_status="Fake status",
                    confidence=0.9,
                    short_notes="Mislabelled fixture.",
                    sources=("test://mislabelled",),
                    classifier_version=self.classifier_version,
                    is_stub=False,
                )

        run = ClassificationPipeline(MislabelledStub()).classify_capture(
            capture(None), image=valid_image()
        )
        diagnostic = format_diagnostic(run)

        self.assertEqual(run.status, ClassificationStatus.ERROR)
        self.assertTrue(run.result.is_stub)
        self.assertEqual(run.result.demo_label, "DEMO DATA")
        self.assertIn("provenance do not match", run.result.error)
        self.assertIn("DEMO DATA", diagnostic)
        self.assertNotIn("PRODUCTION MODEL", diagnostic)


if __name__ == "__main__":
    unittest.main()
