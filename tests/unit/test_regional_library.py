from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from botanika.core.settings import DEFAULT_REGIONAL_CATALOG, DEFAULT_SPECIES_CATALOG
from botanika.knowledge import load_regional_catalog, KnowledgeStore
from botanika.storage import DiscoveryLibrary
from botanika.vision.classification import (
    ClassificationPipeline,
    ClassificationResult,
    ClassificationStatus,
)
from botanika.vision.detection import BoundingBox
from botanika.vision.quality import CropStore


class RegionalLibraryTests(unittest.TestCase):
    def test_regional_catalog_is_broader_than_classifier_and_sourced(self):
        catalog = load_regional_catalog(DEFAULT_REGIONAL_CATALOG)
        self.assertGreaterEqual(len(catalog["species"]), 20)
        self.assertIn("occurrence_basis", catalog)
        self.assertIn("gbif-vellore-plantae-search", {
            source["source_id"] for source in catalog["sources"]
        })
        self.assertTrue(all(item["source_ids"] for item in catalog["species"]))
        self.assertTrue(all(item["knowledge"] for item in catalog["species"]))

    def test_same_species_groups_photos_and_locations_with_safe_map_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = KnowledgeStore(root / "botanika.sqlite", DEFAULT_SPECIES_CATALOG)
            library = DiscoveryLibrary(root / "botanika.sqlite", root / "media", clock=lambda: 1000.0)
            self.addCleanup(library.close)
            self.addCleanup(knowledge.close)
            crops = CropStore(root / "transient")
            first = crops.save(np.full((110, 110, 3), 80, dtype=np.uint8), BoundingBox(5, 5, 100, 100))
            second = crops.save(np.full((110, 110, 3), 160, dtype=np.uint8), BoundingBox(5, 5, 100, 100))
            run_one = _run(first, "first")
            run_two = _run(second, "second")
            first_saved = library.save(first, run_one, observed_at=1000, position={"latitude": 12.92, "longitude": 79.13, "accuracy_m": 8, "source": "test"})
            # The same crop inside the accidental-save window stays one
            # photo, while a new location is retained as another marker.
            repeated = library.save(first, run_one, observed_at=1000.5, position={"latitude": 12.95, "longitude": 79.16, "accuracy_m": 9, "source": "test"})
            self.assertEqual(repeated.id, first_saved.id)
            self.assertEqual(len(repeated.locations), 2)
            library.save(second, run_two, observed_at=1001, position={"latitude": 12.93, "longitude": 79.14, "accuracy_m": 10, "source": "test"})
            groups = library.list_grouped()
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["observation_count"], 2)
            self.assertEqual(len(groups[0]["locations"]), 3)
            self.assertEqual(len(library.list_locations()), 3)
            self.assertTrue(all(item["directions_url"].startswith("https://www.google.com/maps/dir/") for item in library.list_locations()))


def _run(capture, request_id: str):
    class FixedClassifier:
        classifier_version = "test"
        is_stub = False

        def classify(self, crop, **kwargs):
            return ClassificationResult(
                status=ClassificationStatus.ACCEPTED,
                species_id="in:ficus-benghalensis",
                common_name="Banyan",
                scientific_name="Ficus benghalensis",
                family="Moraceae",
                category="Indian native",
                conservation_status="Not threatened",
                confidence=0.9,
                short_notes="Aerial roots.",
                sources=("https://powo.science.kew.org/taxon/urn:lsid:ipni.org:names:852482-1/general-information",),
                classifier_version=self.classifier_version,
            )

    return ClassificationPipeline(FixedClassifier()).classify_capture(capture, request_id=request_id)


if __name__ == "__main__":
    unittest.main()
