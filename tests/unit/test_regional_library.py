from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from botanika.core.settings import DEFAULT_REGIONAL_CATALOG, DEFAULT_SPECIES_CATALOG
from botanika.knowledge import (
    CatalogIntegrityError,
    KnowledgeStore,
    load_reference_catalog,
    load_regional_catalog,
)
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
        self.assertGreaterEqual(len(catalog["species"]), 48)
        self.assertIn("occurrence_basis", catalog)
        self.assertIn("gbif-vellore-plantae-search", {
            source["source_id"] for source in catalog["sources"]
        })
        self.assertTrue(all(item["source_ids"] for item in catalog["species"]))
        self.assertTrue(all(item["knowledge"] for item in catalog["species"]))

    def test_reference_catalog_joins_reviewed_campus_labels_without_merging_model_catalog(self):
        reference = load_reference_catalog(DEFAULT_REGIONAL_CATALOG)
        self.assertEqual(reference.version, "2026.09.05.1")
        self.assertEqual(reference.species_by_id()["in:sanchezia-oblonga"].scientific_name, "Sanchezia oblonga")
        self.assertNotEqual(
            reference.species_by_id()["in:sanchezia-oblonga"].species_id,
            "in:pseuderanthemum-maculatum",
        )
        self.assertEqual(
            reference.species_by_id()["in:cordia-sebestena"].scientific_name,
            "Cordia sebestena",
        )
        self.assertIn("Mimusops elengi", reference.species_by_id()["in:mimusops-elengi"].scientific_name)

        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(
                Path(directory) / "botanika.sqlite",
                DEFAULT_SPECIES_CATALOG,
                reference_catalog_path=DEFAULT_REGIONAL_CATALOG,
            )
            self.addCleanup(store.close)
            # The seven-class production catalog remains unchanged while the
            # reference species are available to library/knowledge callers.
            self.assertEqual(len(store.catalog.species), 7)
            self.assertEqual(len(store.list_species()), 48)
            self.assertEqual(store.get_species("in:serissa-japonica").common_name, "Snowrose")
            answer = store.answer("What is Sanchezia oblonga?")
            self.assertFalse(answer.abstained)
            self.assertTrue(all(hit.species_id == "in:sanchezia-oblonga" for hit in answer.citations))
            self.assertTrue(all(hit.source_url.startswith("https://") for hit in answer.citations))
            manifest = store.knowledge_manifest()
            self.assertEqual(
                manifest["reference_catalog"]["digest"],
                reference.digest,
            )
            self.assertEqual(manifest["reference_catalog"]["version"], reference.version)

    def test_reference_digest_requires_version_bump_and_allows_versioned_metadata_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "regional.json"
            catalog_path.write_text(DEFAULT_REGIONAL_CATALOG.read_text(encoding="utf-8"), encoding="utf-8")
            database = root / "botanika.sqlite"
            first = KnowledgeStore(database, DEFAULT_SPECIES_CATALOG, reference_catalog_path=catalog_path)
            first.close()

            import json

            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
            target = next(item for item in raw["species"] if item["species_id"] == "in:serissa-japonica")
            target["short_notes"] += " Revised."
            old_fact = target["knowledge"][0]["text"]
            target["knowledge"][0]["text"] = "This is the replacement versioned fact for Snowrose."
            catalog_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(CatalogIntegrityError, "without a catalog version bump"):
                KnowledgeStore(database, DEFAULT_SPECIES_CATALOG, reference_catalog_path=catalog_path)

            raw["version"] = "2026.09.05.2"
            catalog_path.write_text(json.dumps(raw), encoding="utf-8")
            revised = KnowledgeStore(database, DEFAULT_SPECIES_CATALOG, reference_catalog_path=catalog_path)
            self.addCleanup(revised.close)
            self.assertTrue(revised.get_species("in:serissa-japonica").short_notes.endswith("Revised."))
            self.assertTrue(
                revised.search(
                    "replacement versioned fact",
                    species_id="in:serissa-japonica",
                    use_embedding=False,
                )
            )
            self.assertFalse(
                revised.search(
                    old_fact,
                    species_id="in:serissa-japonica",
                    use_embedding=False,
                )
            )

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
            self.assertEqual(
                {
                    item["directions_url"] for item in library.list_locations()
                },
                {
                    "https://www.google.com/maps/dir/?api=1&destination=12.9200000%2C79.1300000&travelmode=walking&dir_action=navigate",
                    "https://www.google.com/maps/dir/?api=1&destination=12.9500000%2C79.1600000&travelmode=walking&dir_action=navigate",
                    "https://www.google.com/maps/dir/?api=1&destination=12.9300000%2C79.1400000&travelmode=walking&dir_action=navigate",
                },
            )


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
