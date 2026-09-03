from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import numpy as np

from botanika.core.settings import DEFAULT_SPECIES_CATALOG
from botanika.knowledge import KnowledgeStore
from botanika.storage import DiscoveryError, DiscoveryLibrary
from botanika.vision.classification import (
    ClassificationPipeline,
    ClassificationResult,
    ClassificationStatus,
)
from botanika.vision.detection import BoundingBox
from botanika.vision.quality import CropStore


class Phase6LibraryTests(unittest.TestCase):
    def test_groups_repeated_species_deduplicates_and_keeps_thumbnails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = KnowledgeStore(root / "botanika.sqlite", DEFAULT_SPECIES_CATALOG)
            library = DiscoveryLibrary(root / "botanika.sqlite", root / "media", clock=lambda: 1000.0)
            self.addCleanup(library.close)
            self.addCleanup(knowledge.close)
            crops = CropStore(root / "transient")

            first = crops.save(np.full((140, 160, 3), 90, dtype=np.uint8), BoundingBox(20, 20, 120, 120))
            second = crops.save(np.full((140, 160, 3), 160, dtype=np.uint8), BoundingBox(30, 20, 130, 120))
            run_one = _production_run(first, "request-one")
            run_two = _production_run(second, "request-two")

            saved = library.save(first, run_one, observed_at=1000.0)
            duplicate = library.save(first, run_one, observed_at=1000.0)
            self.assertEqual(saved.id, duplicate.id)
            library.save(second, run_two, observed_at=1001.0)

            groups = library.list_grouped()
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["observation_count"], 2)
            self.assertEqual(len(library.list_records()), 2)
            self.assertEqual(len([path for path in (root / "media").rglob("*") if path.is_file()]), 4)

            reopened = DiscoveryLibrary(root / "botanika.sqlite", root / "media", clock=lambda: 1000.0)
            self.addCleanup(reopened.close)
            self.assertEqual(len(reopened.list_records()), 2)
            self.assertEqual(len([path for path in (root / "media").rglob("*") if path.is_file()]), 4)

    def test_export_delete_restore_preserves_image_linkage_with_knowledge_open(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = KnowledgeStore(root / "botanika.sqlite", DEFAULT_SPECIES_CATALOG)
            library = DiscoveryLibrary(root / "botanika.sqlite", root / "media", clock=lambda: 2000.0)
            self.addCleanup(library.close)
            self.addCleanup(knowledge.close)
            crops = CropStore(root / "transient")
            capture = crops.save(np.full((120, 120, 3), 130, dtype=np.uint8), BoundingBox(10, 10, 100, 100))
            record = library.save(capture, _production_run(capture, "request-export"), observed_at=2000.0)
            archive = library.export_archive(root / "backup.zip")

            self.assertTrue(library.delete(record.id, confirmed=True))
            self.assertEqual(library.list_records(), [])
            self.assertEqual(len([path for path in (root / "media").rglob("*") if path.is_file()]), 0)
            library.restore_archive(archive, confirmed=True)
            restored = library.list_records()
            self.assertEqual([item.id for item in restored], [record.id])
            self.assertTrue(restored[0].crop_path.is_file())
            self.assertTrue((root / "media" / restored[0].thumbnail_path).is_file())
            self.assertTrue(knowledge.search("banyan"))

    def test_quota_rejects_second_observation_without_orphaning_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = KnowledgeStore(root / "botanika.sqlite", DEFAULT_SPECIES_CATALOG)
            library = DiscoveryLibrary(
                root / "botanika.sqlite",
                root / "media",
                quota_observations=1,
                clock=lambda: 3000.0,
            )
            self.addCleanup(library.close)
            self.addCleanup(knowledge.close)
            crops = CropStore(root / "transient")
            first = crops.save(np.full((100, 100, 3), 40, dtype=np.uint8), BoundingBox(10, 10, 90, 90))
            second = crops.save(np.full((100, 100, 3), 210, dtype=np.uint8), BoundingBox(10, 10, 90, 90))
            library.save(first, _production_run(first, "request-quota-one"))
            with self.assertRaises(DiscoveryError):
                library.save(second, _production_run(second, "request-quota-two"))
            self.assertEqual(len(library.list_records()), 1)
            self.assertEqual(len([path for path in (root / "media").rglob("*") if path.is_file()]), 2)

    def test_note_category_position_and_crop_only_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = KnowledgeStore(root / "botanika.sqlite", DEFAULT_SPECIES_CATALOG)
            library = DiscoveryLibrary(root / "botanika.sqlite", root / "media", clock=lambda: 4000.0)
            self.addCleanup(library.close)
            self.addCleanup(knowledge.close)
            capture = CropStore(root / "transient").save(
                np.full((180, 220, 3), 120, dtype=np.uint8),
                BoundingBox(50, 40, 150, 140),
            )
            record = library.save(
                capture,
                _production_run(capture, "request-metadata"),
                note="Garden edge",
                position={"latitude": 12.9, "longitude": 77.6, "accuracy_m": 8.0, "source": "test"},
            )
            self.assertLess(record.width, 220)
            self.assertLess(record.height, 180)
            self.assertEqual([item.id for item in library.list_records(category="Indian native")], [record.id])
            self.assertEqual(library.list_records(category="Western Ghats native"), [])
            updated = library.update_note(record.id, "Updated note")
            self.assertEqual(updated.note, "Updated note")
            with library.database.transaction(immediate=False) as connection:
                position_count = connection.execute(
                    "SELECT COUNT(*) FROM positioning_samples WHERE observation_id = ?",
                    (record.id,),
                ).fetchone()[0]
            self.assertEqual(position_count, 1)

    def test_failed_restore_keeps_original_database_and_media(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_knowledge = KnowledgeStore(root / "source.sqlite", DEFAULT_SPECIES_CATALOG)
            source = DiscoveryLibrary(root / "source.sqlite", root / "source-media", clock=lambda: 5000.0)
            self.addCleanup(source.close)
            self.addCleanup(source_knowledge.close)
            source_capture = CropStore(root / "source-temp").save(
                np.full((100, 100, 3), 70, dtype=np.uint8), BoundingBox(10, 10, 90, 90)
            )
            source.save(source_capture, _production_run(source_capture, "source"))
            archive = source.export_archive(root / "backup.zip")

            current_knowledge = KnowledgeStore(root / "current.sqlite", DEFAULT_SPECIES_CATALOG)
            current = DiscoveryLibrary(root / "current.sqlite", root / "current-media", clock=lambda: 6000.0)
            self.addCleanup(current.close)
            self.addCleanup(current_knowledge.close)
            current_capture = CropStore(root / "current-temp").save(
                np.full((100, 100, 3), 190, dtype=np.uint8), BoundingBox(10, 10, 90, 90)
            )
            original = current.save(current_capture, _production_run(current_capture, "current"))

            with mock.patch(
                "botanika.storage.discoveries.shutil.copyfile",
                side_effect=OSError("simulated staged-media failure"),
            ):
                with self.assertRaisesRegex(OSError, "simulated staged-media failure"):
                    current.restore_archive(archive, confirmed=True)

            records = current.list_records()
            self.assertEqual([item.id for item in records], [original.id])
            self.assertTrue(records[0].crop_path.is_file())
            self.assertTrue((root / "current-media" / records[0].thumbnail_path).is_file())

            restore_from = current.database.restore_from

            def fail_new_database(path):
                if Path(path).name == "database.sqlite":
                    raise OSError("simulated database restore failure")
                return restore_from(path)

            with mock.patch.object(
                current.database,
                "restore_from",
                side_effect=fail_new_database,
            ):
                with self.assertRaisesRegex(OSError, "simulated database restore failure"):
                    current.restore_archive(archive, confirmed=True)

            records = current.list_records()
            self.assertEqual([item.id for item in records], [original.id])
            self.assertTrue(records[0].crop_path.is_file())
            self.assertTrue((root / "current-media" / records[0].thumbnail_path).is_file())


def _production_run(capture, request_id: str):
    result = ClassificationResult(
        status=ClassificationStatus.ACCEPTED,
        species_id="in:ficus-benghalensis",
        common_name="Banyan",
        scientific_name="Ficus benghalensis",
        family="Moraceae",
        category="Indian native",
        conservation_status="Not threatened",
        confidence=0.91,
        short_notes="Aerial roots can form additional trunks.",
        sources=("https://powo.science.kew.org/",),
        classifier_version="india-starter-feature-1.0.0",
    )
    return ClassificationPipeline(_FixedClassifier()).classify_capture(capture, request_id=request_id)


class _FixedClassifier:
    classifier_version = "india-starter-feature-1.0.0"
    is_stub = False

    def classify(self, crop, *, cancellation=None):
        return ClassificationResult(
            status=ClassificationStatus.ACCEPTED,
            species_id="in:ficus-benghalensis",
            common_name="Banyan",
            scientific_name="Ficus benghalensis",
            family="Moraceae",
            category="Indian native",
            conservation_status="Not threatened",
            confidence=0.91,
            short_notes="Aerial roots can form additional trunks.",
            sources=("https://powo.science.kew.org/",),
            classifier_version=self.classifier_version,
        )


if __name__ == "__main__":
    unittest.main()
