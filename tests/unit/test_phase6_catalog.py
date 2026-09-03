from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest
from unittest import mock

import numpy as np

from botanika.core.settings import DEFAULT_CLASSIFIER_MODEL, DEFAULT_SPECIES_CATALOG
from botanika.core.capabilities import CapabilitiesReport, CapabilityState
from botanika.knowledge import KnowledgeStore, load_catalog
from botanika.storage import SQLiteDatabase
from botanika.vision.classification import (
    ClassificationStatus,
    CompactSpeciesClassifier,
)


class Phase6CatalogTests(unittest.TestCase):
    def test_catalog_has_immutable_species_join_and_provenance(self):
        catalog = load_catalog(DEFAULT_SPECIES_CATALOG)
        self.assertEqual(len(catalog.species), 7)
        self.assertEqual(set(catalog.label_map.values()), {item.species_id for item in catalog.species})
        self.assertTrue(all(item.source_ids for item in catalog.species))
        self.assertTrue(any(item.is_native for item in catalog.species))
        self.assertEqual(catalog.model_release.artifact_sha256, _sha256(DEFAULT_CLASSIFIER_MODEL))
        sources = {item.source_id: item for item in catalog.sources}
        for species in catalog.species:
            for fact in species.knowledge:
                source = sources[fact.source_id]
                self.assertNotIn(source.url, {"https://powo.science.kew.org/", "https://www.iucnredlist.org/"})
                self.assertTrue(source.license)
                self.assertTrue(source.license_url)

    def test_compact_classifier_rejects_out_of_catalog_view_without_stub_label(self):
        classifier = CompactSpeciesClassifier(DEFAULT_CLASSIFIER_MODEL, DEFAULT_SPECIES_CATALOG)
        result = classifier.classify(np.zeros((96, 96, 3), dtype=np.uint8))

        self.assertFalse(classifier.is_stub)
        self.assertFalse(result.is_stub)
        self.assertEqual(result.status, ClassificationStatus.UNCERTAIN)
        self.assertIsNone(result.species_id)
        self.assertLessEqual(len(result.suggestions), 3)

    def test_compact_classifier_abstains_when_release_evidence_is_incomplete(self):
        classifier = CompactSpeciesClassifier(DEFAULT_CLASSIFIER_MODEL, DEFAULT_SPECIES_CATALOG)
        target = classifier._centroids[0].copy()
        with mock.patch(
            "botanika.vision.classification.compact.extract_features",
            return_value=target,
        ):
            result = classifier.classify(np.full((96, 96, 3), 100, dtype=np.uint8))
        self.assertEqual(result.status, ClassificationStatus.UNCERTAIN)
        self.assertIsNone(result.species_id)
        self.assertFalse(result.is_stub)
        self.assertFalse(classifier.deployment_ready)
        self.assertIn("field validation is incomplete", result.short_notes)

    def test_compact_classifier_accepts_catalog_join_after_release_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog_path = Path(directory) / "validated-catalog.json"
            raw = json.loads(DEFAULT_SPECIES_CATALOG.read_text(encoding="utf-8"))
            species_ids = [item["species_id"] for item in raw["species"]]
            raw["version"] = "2026.09.validated-test"
            raw["model_release"]["metrics"] = {
                "macro_f1": 0.85,
                "unknown_rejection_rate": 0.91,
                "held_out_observations": 140,
                "per_class": {species_id: {"f1": 0.8} for species_id in species_ids},
                "pi_benchmark": {
                    "latency_p95_ms": 42.0,
                    "peak_memory_mb": 180.0,
                    "max_temperature_c": 68.0,
                },
            }
            catalog_path.write_text(json.dumps(raw), encoding="utf-8")
            classifier = CompactSpeciesClassifier(DEFAULT_CLASSIFIER_MODEL, catalog_path)
            with mock.patch(
                "botanika.vision.classification.compact.extract_features",
                return_value=classifier._centroids[0].copy(),
            ):
                result = classifier.classify(np.full((96, 96, 3), 100, dtype=np.uint8))
            self.assertTrue(classifier.deployment_ready)
            self.assertEqual(result.status, ClassificationStatus.ACCEPTED)
            self.assertEqual(result.species_id, classifier.label_map[0])
            self.assertTrue(all(source.startswith("https://") for source in result.sources))

    def test_knowledge_store_seeds_fts_citations_and_explicit_abstention(self):
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(Path(directory) / "botanika.sqlite", DEFAULT_SPECIES_CATALOG)
            self.addCleanup(store.close)

            self.assertEqual(len(store.list_species()), 7)
            with store.database.transaction(immediate=False) as connection:
                chunk_count = connection.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]
            self.assertEqual(chunk_count, 14)
            self.assertEqual(store.list_species(query="tulsi")[0].species_id, "in:ocimum-tenuiflorum")
            answer = store.answer("Where is the banyan native?")
            self.assertFalse(answer.abstained)
            self.assertTrue(answer.citations)
            self.assertTrue(all(item.source_url for item in answer.citations))
            unknown = store.answer("What is the moon made of?")
            self.assertTrue(unknown.abstained)
            self.assertEqual(store.active_model_release()["version"], "india-starter-feature-1.0.0")

    def test_species_scoped_search_filters_before_limiting(self):
        with tempfile.TemporaryDirectory() as directory:
            store = KnowledgeStore(Path(directory) / "botanika.sqlite", DEFAULT_SPECIES_CATALOG)
            self.addCleanup(store.close)
            expected = {
                "in:ficus-benghalensis",
                "in:ficus-religiosa",
                "in:artocarpus-heterophyllus",
                "in:ocimum-tenuiflorum",
                "in:moringa-oleifera",
                "in:jasminum-sambac",
                "in:syzygium-microphyllum",
            }
            for species_id in expected:
                hits = store.search("native", species_id=species_id, limit=1)
                self.assertEqual([item.species_id for item in hits], [species_id])

    def test_catalog_revision_requires_version_bump_and_rebuilds_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "botanika.sqlite"
            catalog_path = root / "catalog.json"
            raw = json.loads(DEFAULT_SPECIES_CATALOG.read_text(encoding="utf-8"))
            catalog_path.write_text(json.dumps(raw), encoding="utf-8")
            first = KnowledgeStore(database, catalog_path)
            first.close()

            raw["sources"][0]["title"] += " revised"
            catalog_path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "without a catalog version bump"):
                KnowledgeStore(database, catalog_path)

            raw["version"] = "2026.09.3"
            catalog_path.write_text(json.dumps(raw), encoding="utf-8")
            revised = KnowledgeStore(database, catalog_path)
            self.addCleanup(revised.close)
            self.assertEqual(revised.catalog_version, "2026.09.3")
            self.assertTrue(revised.source(raw["sources"][0]["source_id"])["title"].endswith(" revised"))

    def test_readiness_requires_classifier_knowledge_library_storage_and_preview(self):
        ready = CapabilityState("ready", True, "ready")
        unavailable = CapabilityState("classifier", False, "missing model")
        report = CapabilitiesReport(
            camera=unavailable,
            detector=unavailable,
            classifier=unavailable,
            knowledge=ready,
            storage=ready,
            library=ready,
            preview=ready,
        )
        self.assertFalse(report.ready)

    def test_schema_migration_adds_native_flag_to_phase6_v1_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite"
            connection = sqlite3.connect(path)
            connection.execute("CREATE TABLE botanika_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
            connection.execute("INSERT INTO botanika_migrations VALUES (1, 'test')")
            connection.execute("CREATE TABLE species(species_id TEXT PRIMARY KEY)")
            connection.commit()
            connection.close()

            database = SQLiteDatabase(path)
            self.addCleanup(database.close)
            with database.transaction(immediate=False) as migrated:
                columns = {row[1] for row in migrated.execute("PRAGMA table_info(species)")}
                versions = {row[0] for row in migrated.execute("SELECT version FROM botanika_migrations")}
            self.assertIn("is_native", columns)
            self.assertIn(2, versions)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
