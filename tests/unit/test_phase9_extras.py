"""Maintainable deterministic checks for the Phase 9 extras."""

from __future__ import annotations

import base64
import asyncio
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

import cv2
import numpy as np

from botanika.core.settings import AppSettings
from botanika.api.concurrency import run_blocking
from botanika.knowledge import KnowledgeStore
from botanika.knowledge.llm import validate_grounded_output
from botanika.storage import DiscoveryLibrary, WeedObservationStore
from botanika.vision.detection import BoundingBox, Detection
from botanika.vision.weeds import WeedService
from botanika.voice import AudioCoordinator, VoiceState


CATALOG = Path(__file__).resolve().parents[2] / "config" / "catalog" / "india-starter-species.json"
WEED_MANIFEST = Path(__file__).resolve().parents[2] / "config" / "weed" / "phase9-beta.json"


class Phase9ExtraTests(unittest.TestCase):
    def test_progress_repeat_delete_and_export_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            knowledge = KnowledgeStore(root / "database.sqlite", CATALOG)
            catalog = tuple(knowledge.catalog.species)
            knowledge.close()
            library = DiscoveryLibrary(root / "database.sqlite", root / "discoveries")
            self.addCleanup(library.database.close)

            self.assertEqual(library.progress(catalog)["discovered_species"], 0)
            first = self._insert_discovery(library, "first", observed_at=10.0)
            second = self._insert_discovery(library, "second", observed_at=20.0)
            progress = library.progress(catalog)
            self.assertEqual(progress["discovered_species"], 1)
            self.assertEqual(progress["observation_count"], 2)
            self.assertEqual(progress["repeat_discoveries"], 1)
            self.assertTrue(progress["discovery_indicators"][0]["repeat_discovery"])

            archive = library.export_archive(root / "backups" / "library.zip")
            self.assertTrue(archive.is_file())
            self.assertTrue(library.delete(first, confirmed=True))
            self.assertEqual(library.progress(catalog)["observation_count"], 1)
            self.assertEqual(library.progress(catalog)["repeat_discoveries"], 0)
            library.restore_archive(archive, confirmed=True)
            restored = library.progress(catalog)
            self.assertEqual(restored["observation_count"], 2)
            self.assertEqual(restored["repeat_discoveries"], 1)
            self.assertTrue(library.get(first).crop_path.is_file())
            self.assertTrue(library.get(second).crop_path.is_file())

    def test_weed_position_and_detection_persistence_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = AppSettings(
                database_path=root / "database.sqlite",
                discoveries_dir=root / "discoveries",
                weed_manifest_path=WEED_MANIFEST,
            )
            observations = WeedObservationStore(database_path=settings.database_path)
            self.addCleanup(observations.close)

            class Detector:
                def __init__(self, values):
                    self.values = values

                def detect(self, _image):
                    return self.values

            boxes = [
                Detection(0, "parthenium", 0.9, BoundingBox(2, 3, 30, 40)),
                Detection(1, "nutsedge", 0.8, BoundingBox(50, 60, 90, 120)),
            ]
            service = WeedService(settings, detector=Detector(boxes), observation_store=observations)
            image = np.zeros((160, 240, 3), dtype=np.uint8)
            for invalid_position in (
                None,
                {"latitude": 18.5, "longitude": 73.8, "accuracy_m": 10},
                {"latitude": 18.5, "longitude": 73.8, "accuracy_m": 101, "source": "test"},
                {"latitude": 18.5, "longitude": 73.8, "accuracy_m": 10, "source": "  "},
            ):
                result = service.detect_image(image, position=invalid_position)
                self.assertEqual(result["position_message"], "Exact location could not be found. Coordinate collection was skipped.")
                self.assertIsNone(result["run_id"])
            self.assertEqual(observations.count(), 0)
            self.assertEqual(observations.run_count(), 0)

            result = service.detect_image(
                image,
                position={"latitude": 18.5, "longitude": 73.8, "accuracy_m": 10, "source": "test", "timestamp": 100},
            )
            self.assertTrue(result["position_available"])
            self.assertEqual(observations.count(), 2)
            self.assertEqual(observations.run_count(), 1)
            with observations.database.transaction(immediate=False) as connection:
                stored = connection.execute("SELECT detections_json FROM weed_runs").fetchone()[0]
            self.assertNotIn("x1", stored)
            self.assertFalse(result["image_persisted"])

            empty = WeedService(settings, detector=Detector([]), observation_store=observations)
            empty_result = empty.detect_image(
                image,
                position={"latitude": 18.5, "longitude": 73.8, "accuracy_m": 10, "source": "test", "timestamp": 100},
            )
            self.assertIsNone(empty_result["run_id"])
            self.assertEqual(observations.run_count(), 1)

            transient = service.detect_image(image, include_frame=True)
            encoded = transient["frame_data_url"].split(",", 1)[1]
            self.assertEqual(base64.b64decode(encoded)[:2], b"\xff\xd8")
            self.assertFalse(any(root.rglob("*.jpg")))

    def test_audio_listen_interrupt_is_explicit_and_state_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = AppSettings(
                database_path=Path(directory) / "database.sqlite",
                stt_models_path=Path(directory) / "stt",
                tts_models_path=Path(directory) / "tts",
            )
            coordinator = AudioCoordinator(settings)
            entered = threading.Event()

            class InputStream:
                def __init__(self, **_kwargs):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

                def read(self, _chunk_size):
                    entered.set()
                    coordinator._interrupt.wait(timeout=2.0)
                    return np.zeros((10, 1), dtype=np.int16), False

            fake_sounddevice = types.SimpleNamespace(InputStream=InputStream)
            with mock.patch.object(coordinator, "_audio_devices", return_value=(True, False, None)), \
                    mock.patch.object(coordinator, "_ensure_stt", return_value=object()), \
                    mock.patch.dict(sys.modules, {"sounddevice": fake_sounddevice}):
                result_holder = []
                worker = threading.Thread(target=lambda: result_holder.append(coordinator.listen_once()))
                worker.start()
                self.assertTrue(entered.wait(timeout=1.0))
                interrupted = coordinator.interrupt()
                self.assertTrue(interrupted["interrupted"])
                worker.join(timeout=2.0)
            self.assertFalse(worker.is_alive())
            self.assertEqual(result_holder[0]["status"], "interrupted")
            self.assertTrue(result_holder[0]["interrupted"])
            self.assertEqual(coordinator.status().state, VoiceState.UNAVAILABLE.value)

    def test_grounded_llm_requires_citations_per_statement(self):
        self.assertFalse(validate_grounded_output("Banyan is native [chunk-a]. It has aerial roots.", {"chunk-a"}))
        self.assertTrue(validate_grounded_output("Banyan is native [chunk-a]. It has aerial roots [chunk-a].", {"chunk-a"}))
        self.assertFalse(validate_grounded_output("Banyan is native [chunk-a]. it has aerial roots.", {"chunk-a"}))
        self.assertFalse(validate_grounded_output("Banyan is native [chunk-a].", {"chunk-b"}))
        self.assertFalse(validate_grounded_output("[chunk-a]", {"chunk-a"}))

    def test_production_environment_wires_state_paths(self):
        settings = AppSettings.from_environment(
            {
                "BOTANIKA_NETWORK_ENABLED": "true",
                "BOTANIKA_HOST": "0.0.0.0",
                "BOTANIKA_LOOPBACK_ONLY": "false",
                "BOTANIKA_DATABASE_PATH": "/var/lib/botanika/database/botanika.sqlite",
                "BOTANIKA_TEMP_CROPS_DIR": "/var/lib/botanika/temp/phase6-crops",
                "BOTANIKA_DISCOVERIES_DIR": "/var/lib/botanika/discoveries",
                "BOTANIKA_BACKUP_DIR": "/var/lib/botanika/backups",
            }
        )
        self.assertEqual(settings.database_path, Path("/var/lib/botanika/database/botanika.sqlite"))
        self.assertEqual(settings.temp_crops_dir, Path("/var/lib/botanika/temp/phase6-crops"))
        self.assertEqual(settings.discoveries_dir, Path("/var/lib/botanika/discoveries"))
        self.assertEqual(settings.backup_dir, Path("/var/lib/botanika/backups"))

        project_root = Path(__file__).resolve().parents[2]
        backend_unit = (project_root / "deploy/systemd/botanika-backend.service").read_text(encoding="utf-8")
        self.assertIn("User=botanika", backend_unit)
        self.assertIn("SupplementaryGroups=video render audio gpio", backend_unit)

    @staticmethod
    def _insert_discovery(library: DiscoveryLibrary, suffix: str, *, observed_at: float) -> str:
        species_id = "in:ficus-benghalensis"
        observation_id = f"observation-{suffix}"
        relative = f"{species_id}/{suffix}.png"
        image = np.full((20, 24, 3), 80, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        assert ok
        payload = encoded.tobytes()
        crop = library.media_dir / relative
        crop.parent.mkdir(parents=True, exist_ok=True)
        crop.write_bytes(payload)
        thumbnail_relative = f"{species_id}/{suffix}.thumb.jpg"
        thumbnail = library.media_dir / thumbnail_relative
        thumbnail.write_bytes(payload)
        crop_hash = hashlib.sha256(payload).hexdigest()
        with library.database.transaction() as connection:
            connection.execute(
                "INSERT INTO discoveries(observation_id, species_id, observed_at, saved_at, confidence, classifier_version, request_id, result_snapshot, note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (observation_id, species_id, observed_at, observed_at, 0.9, "test", suffix, json.dumps({"sources": []}), None),
            )
            connection.execute(
                "INSERT INTO discovery_images(image_id, observation_id, crop_path, thumbnail_path, crop_hash, width, height, mime_type, byte_size, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"image-{suffix}", observation_id, relative, thumbnail_relative, crop_hash, 24, 20, "image/png", len(payload) * 2, observed_at),
            )
            connection.execute(
                "INSERT INTO library_species(species_id, first_seen, last_seen, observation_count) VALUES (?, ?, ?, 1) ON CONFLICT(species_id) DO UPDATE SET last_seen=excluded.last_seen, observation_count=observation_count + 1",
                (species_id, observed_at, observed_at),
            )
        return observation_id


class Phase9ConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocking_bridge_supports_kwargs_and_propagates_worker_errors(self):
        result = await asyncio.wait_for(run_blocking(_add_values, 2, right=3), timeout=1.0)
        self.assertEqual(result, 5)
        with self.assertRaisesRegex(RuntimeError, "worker failed"):
            await asyncio.wait_for(run_blocking(_raise_worker), timeout=1.0)


def _add_values(left: int, *, right: int) -> int:
    return left + right


def _raise_worker() -> None:
    raise RuntimeError("worker failed")


if __name__ == "__main__":
    unittest.main()
