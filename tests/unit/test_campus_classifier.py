from __future__ import annotations

from pathlib import Path
import hashlib
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from botanika.core.settings import DEFAULT_SPECIES_CATALOG
from botanika.knowledge import KnowledgeStore
from botanika.storage import DiscoveryLibrary
from botanika.vision.classification import (
    ClassificationPipeline,
    ClassificationResult,
    ClassificationStatus,
    CAMPUS_ARTIFACT_FORMAT,
    CampusFewShotClassifier,
    EnrollmentError,
    build_enrollment_artifact,
    campus_label_id,
    perceptual_hash,
    preprocess_image,
    score_labels,
)
from botanika.vision.classification.fewshot import _find_duplicates, accepted_label_index
from botanika.vision.classification.embedding import (
    MOBILENETV2_LICENSE,
    MOBILENETV2_LICENSE_URL,
    MOBILENETV2_MODEL_CARD,
    MOBILENETV2_MODEL_ID,
    MOBILENETV2_SHA256,
    MOBILENETV2_SOURCE,
    MOBILENETV2_VERSION,
    canonical_json,
)
from botanika.vision.detection import BoundingBox
from botanika.vision.quality import CropStore


class CampusClassifierContractTests(unittest.TestCase):
    def test_label_ids_are_stable_and_path_safe(self):
        self.assertEqual(campus_label_id("  Neem / North Quad  "), "campus:neem-north-quad")
        self.assertEqual(campus_label_id("Ficus benghalensis"), "campus:ficus-benghalensis")
        with self.assertRaises(ValueError):
            campus_label_id("🌱")

    def test_embedding_preprocessing_has_model_contract(self):
        image = np.zeros((320, 480, 3), dtype=np.uint8)
        image[:, :, 1] = 170
        batch = preprocess_image(image)
        self.assertEqual(batch.shape, (1, 3, 224, 224))
        self.assertEqual(batch.dtype, np.float32)
        self.assertTrue(np.isfinite(batch).all())

    def test_prototype_and_nearest_photo_scores_rank_the_matching_label(self):
        query = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
        prototypes = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32)
        samples = [
            np.asarray([[0.98, 0.02, 0.0], [0.95, 0.05, 0.0]], dtype=np.float32),
            np.asarray([[0.0, 1.0, 0.0], [0.1, 0.9, 0.0]], dtype=np.float32),
        ]
        scores = score_labels(query, prototypes, samples)
        self.assertGreater(float(scores[0]), float(scores[1]))

    def test_evaluation_gate_matches_runtime_similarity_margin_and_confidence(self):
        calibration = {
            "unknown_similarity": 0.62,
            "minimum_margin": 0.06,
            "acceptance_threshold": 0.58,
        }
        self.assertEqual(
            accepted_label_index(np.asarray([0.91, 0.40]), calibration),
            0,
        )
        self.assertIsNone(
            accepted_label_index(np.asarray([0.91, 0.88]), calibration)
        )
        self.assertIsNone(
            accepted_label_index(np.asarray([0.70, 0.20]), calibration)
        )

    def test_duplicate_guard_catches_exact_and_near_hashes(self):
        records = [
            {"relative_path": "train/a.jpg", "sha256": "a" * 64, "perceptual_hash": "0000000000000000"},
            {"relative_path": "held-out/a.jpg", "sha256": "a" * 64, "perceptual_hash": "0000000000000001"},
        ]
        duplicates = _find_duplicates(records)
        self.assertTrue(any(item[2] == 0 for item in duplicates))
        self.assertTrue(any(item[2] == 1 for item in duplicates))

    def test_uncatalogued_campus_result_is_storable_without_catalog_facts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = KnowledgeStore(root / "botanika.sqlite", DEFAULT_SPECIES_CATALOG)
            library = DiscoveryLibrary(root / "botanika.sqlite", root / "media", clock=lambda: 100.0)
            self.addCleanup(library.close)
            self.addCleanup(knowledge.close)
            crops = CropStore(root / "temp")
            image = np.full((120, 120, 3), 90, dtype=np.uint8)
            capture = crops.save(image, BoundingBox(10, 10, 110, 110))
            result = ClassificationResult(
                status=ClassificationStatus.ACCEPTED,
                species_id="campus:north-quad-neem",
                common_name="North Quad Neem",
                scientific_name="Uncatalogued campus label",
                family="Not catalogued",
                category="Campus enrolled label",
                conservation_status="Not assessed",
                confidence=0.88,
                short_notes="Recognized from campus enrollment photos. No sourced botanical facts are attached to this label.",
                sources=("botanika:campus-fewshot-enrollment",),
                classifier_version="campus-fewshot-1.0.0",
                catalogued=False,
            )

            run = ClassificationPipeline(_FixedClassifier(result)).classify_capture(
                capture,
                request_id="campus-save",
            )
            saved = library.save(capture, run, observed_at=100.0)

            self.assertEqual(saved.species_id, "campus:north-quad-neem")
            self.assertEqual(saved.common_name, "North Quad Neem")
            self.assertIsNone(knowledge.get_species("campus:north-quad-neem"))
            with library.database.transaction(immediate=False) as connection:
                row = connection.execute(
                    "SELECT scientific_name, family, conservation_status, ecology FROM species WHERE species_id = ?",
                    (saved.species_id,),
                ).fetchone()
            self.assertEqual(row["scientific_name"], "Uncatalogued campus label")
            self.assertEqual(row["family"], "Not catalogued")
            self.assertEqual(row["conservation_status"], "Not assessed")
            self.assertIn("No sourced botanical facts", row["ecology"])

    def test_enrollment_writes_provisional_artifact_and_classification_abstains(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train = root / "train"
            heldout = root / "held-out"
            unknown = root / "unknown"
            for label, base in (("North Tree", (45, 150, 45)), ("Campus Flower", (45, 45, 190))):
                for index in range(5):
                    _write_fixture_image(train / label / f"train-{index}.png", base, index + (0 if label == "North Tree" else 100))
                for group in range(3):
                    _write_fixture_image(
                        heldout / label / f"plant-{group}" / "view.png",
                        base,
                        group + (20 if label == "North Tree" else 120),
                    )
            for index in range(5):
                _write_fixture_image(unknown / f"unknown-{index}.png", (120, 120, 120), 200 + index)
            artifact_path = root / "campus.json"

            with mock.patch(
                "botanika.vision.classification.fewshot.MobileNetV2Embedder",
                _FakeEmbedder,
            ), mock.patch(
                "botanika.vision.classification.fewshot.load_embedding_model",
                side_effect=lambda path, metadata: _FakeEmbedder(path),
            ):
                artifact = build_enrollment_artifact(
                    train,
                    artifact_path,
                    embedding_model_path=root / "fake.onnx",
                    catalog_path=DEFAULT_SPECIES_CATALOG,
                    held_out_dir=heldout,
                    unknown_dir=unknown,
                    min_images_per_label=5,
                    approve_production=False,
                )
                classifier = CampusFewShotClassifier(
                    artifact_path,
                    root / "fake.onnx",
                    DEFAULT_SPECIES_CATALOG,
                )

            self.assertEqual(artifact["format"], CAMPUS_ARTIFACT_FORMAT)
            self.assertEqual(artifact["metrics"]["training_observations"], 10)
            self.assertEqual(artifact["metrics"]["held_out_observations"], 6)
            self.assertEqual(artifact["metrics"]["unknown_observations"], 5)
            self.assertFalse(artifact["deployment_ready"])
            self.assertFalse(classifier.deployment_ready)
            result = classifier.classify(np.full((80, 80, 3), (45, 150, 45), dtype=np.uint8))
            self.assertEqual(result.status, ClassificationStatus.UNCERTAIN)
            self.assertTrue(result.suggestions)
            self.assertFalse(result.suggestions[0].catalogued)

    def test_checksummed_ready_claim_cannot_bypass_failed_evidence_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "train" / "Campus Tree"
            for index in range(2):
                _write_fixture_image(dataset / f"{index}.png", (30, 140, 30), index + 1)
            artifact_path = root / "campus.json"
            with mock.patch(
                "botanika.vision.classification.fewshot.MobileNetV2Embedder",
                _FakeEmbedder,
            ):
                build_enrollment_artifact(
                    root / "train",
                    artifact_path,
                    embedding_model_path=root / "fake.onnx",
                    catalog_path=DEFAULT_SPECIES_CATALOG,
                    min_images_per_label=2,
                )
            raw = json.loads(artifact_path.read_text(encoding="utf-8"))
            raw["deployment_ready"] = True
            raw["artifact_sha256"] = hashlib.sha256(
                canonical_json({key: value for key, value in raw.items() if key != "artifact_sha256"})
            ).hexdigest()
            artifact_path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
            with mock.patch(
                "botanika.vision.classification.fewshot.load_embedding_model",
                side_effect=lambda path, metadata: _FakeEmbedder(path),
            ):
                classifier = CampusFewShotClassifier(
                    artifact_path,
                    root / "fake.onnx",
                    DEFAULT_SPECIES_CATALOG,
                )
            self.assertFalse(classifier.deployment_ready)
            self.assertIn("at least five enrollment images", classifier.deployment_blocker)
            result = classifier.classify(np.full((80, 80, 3), (30, 140, 30), dtype=np.uint8))
            self.assertEqual(result.status, ClassificationStatus.UNCERTAIN)

    def test_enrollment_rejects_near_duplicate_across_splits(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = np.zeros((80, 80, 3), dtype=np.uint8)
            image[:, :40] = (30, 140, 30)
            image[:, 40:] = (40, 150, 40)
            train = root / "train" / "Tree"
            heldout = root / "held-out" / "Tree"
            for index in range(2):
                _write_fixture_image(train / f"{index}.png", (30 + index, 140, 30), 300 + index)
            train_file = train / "duplicate.png"
            train_file.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(train_file), image)
            heldout_file = heldout / "plant-1" / "duplicate.png"
            heldout_file.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(heldout_file), image)
            with mock.patch(
                "botanika.vision.classification.fewshot.MobileNetV2Embedder",
                _FakeEmbedder,
            ):
                with self.assertRaisesRegex(EnrollmentError, "duplicate or near-duplicate"):
                    build_enrollment_artifact(
                        root / "train",
                        root / "campus.json",
                        embedding_model_path=root / "fake.onnx",
                        catalog_path=DEFAULT_SPECIES_CATALOG,
                        held_out_dir=root / "held-out",
                        min_images_per_label=2,
                    )


class _FixedClassifier:
    is_stub = False

    def __init__(self, result: ClassificationResult) -> None:
        self.result = result
        self.classifier_version = result.classifier_version

    def classify(self, crop, *, cancellation=None):
        return self.result


class _FakeEmbedder:
    """Tiny deterministic encoder used to test artifact gates without weights."""

    dimensions = 3

    def __init__(self, path: Path) -> None:
        self.metadata = SimpleNamespace(
            model_id=MOBILENETV2_MODEL_ID,
            version=MOBILENETV2_VERSION,
            runtime="fake-test-runtime",
            artifact_path=Path(path),
            artifact_sha256=MOBILENETV2_SHA256,
            embedding_dimensions=3,
            input_width=224,
            input_height=224,
            source=MOBILENETV2_SOURCE,
            model_card=MOBILENETV2_MODEL_CARD,
            license=MOBILENETV2_LICENSE,
            license_url=MOBILENETV2_LICENSE_URL,
            to_dict=lambda: {
                "model_id": MOBILENETV2_MODEL_ID,
                "version": MOBILENETV2_VERSION,
                "runtime": "fake-test-runtime",
                "artifact_path": str(path),
                "artifact_sha256": MOBILENETV2_SHA256,
                "embedding_dimensions": 3,
                "source": MOBILENETV2_SOURCE,
                "model_card": MOBILENETV2_MODEL_CARD,
                "license": MOBILENETV2_LICENSE,
                "license_url": MOBILENETV2_LICENSE_URL,
            },
        )

    def embed_views(self, image: np.ndarray) -> np.ndarray:
        values = np.asarray(image, dtype=np.float32).mean(axis=(0, 1))
        norm = float(np.linalg.norm(values))
        return values / max(norm, 1e-8)


def _write_fixture_image(path: Path, base: tuple[int, int, int], seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    noise = rng.integers(-8, 9, size=(80, 80, 3), dtype=np.int16)
    image = np.clip(np.asarray(base, dtype=np.int16) + noise, 0, 255).astype(np.uint8)
    # A small deterministic stripe makes dHash collisions between generated
    # fixtures extremely unlikely while preserving the dominant colour cue.
    image[seed % 80, :, :] = np.clip(image[seed % 80, :, :].astype(np.int16) + 20, 0, 255)
    if not cv2.imwrite(str(path), image):
        raise AssertionError(f"could not write fixture image {path}")


if __name__ == "__main__":
    unittest.main()
