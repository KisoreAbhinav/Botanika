"""Phase 5 compatibility and Phase 6 normal-runtime API contract tests.

The FastAPI application is exercised through HTTPX2's ASGI transport with the
camera pipeline's ``start``/``stop`` stubbed so the suite runs on any Pi (no
camera required). Contracts pinned here are consumed by the kiosk frontend.
"""

from __future__ import annotations

import tempfile
import asyncio
from pathlib import Path
from unittest import mock
import unittest

import httpx2

from botanika.api.app import create_app
from botanika.api.runtime import APP_VERSION
from botanika.core.settings import AppSettings


def build_test_settings(tmp: Path) -> AppSettings:
    return AppSettings(
        database_path=tmp / "database" / "test-library.sqlite",
        demo_discoveries_dir=tmp / "media" / "discoveries",
        temp_crops_dir=tmp / "media" / "temp",
    )


class AsgiTestClient:
    """Small synchronous facade over HTTPX2's native ASGI transport."""

    def __init__(self, app) -> None:
        self.app = app
        self.loop = asyncio.new_event_loop()
        self.lifespan = app.router.lifespan_context(app)
        self.loop.run_until_complete(self.lifespan.__aenter__())
        self.client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://testserver",
        )

    def get(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.client.get(path, **kwargs))

    def post(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.client.post(path, **kwargs))

    def delete(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.client.delete(path, **kwargs))

    def patch(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.client.patch(path, **kwargs))

    def close(self) -> None:
        self.loop.run_until_complete(self.client.aclose())
        self.loop.run_until_complete(self.lifespan.__aexit__(None, None, None))
        self.loop.close()


class Phase5ApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        settings = build_test_settings(Path(self._tmp.name))
        # Keep the suite hardware-free: no camera thread, no detector load.
        patcher = mock.patch.multiple(
            "botanika.vision.services.scan.ScanService",
            start=mock.DEFAULT,
            stop=mock.DEFAULT,
        )
        self.patches = patcher.start()
        self.addCleanup(patcher.stop)
        self.app = create_app(settings)
        # The lifespan builds the runtime; entering the client context runs it.
        self.client = AsgiTestClient(self.app)
        self.addCleanup(self.client.close)

    def test_liveness_contract(self):
        response = self.client.get("/api/v1/health/live")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["version"], APP_VERSION)
        self.assertEqual(body["service"], "botanika-api")

    def test_readiness_contract(self):
        response = self.client.get("/api/v1/health/ready")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn(body["status"], ("ok", "degraded"))
        for key in (
            "camera",
            "detector",
            "classifier",
            "knowledge",
            "storage",
            "library",
            "preview",
        ):
            self.assertIn(key, body["capabilities"])
            self.assertIn("available", body["capabilities"][key])

    def test_capabilities_contract(self):
        response = self.client.get("/api/v1/capabilities")
        self.assertEqual(response.status_code, 200)
        capabilities = response.json()
        self.assertFalse(capabilities["knowledge"]["available"])
        self.assertIn("stub", capabilities["classifier"]["detail"])
        self.assertTrue(capabilities["storage"]["available"])
        self.assertFalse(capabilities["preview"]["available"])
        self.assertIn("not running", capabilities["preview"]["detail"])

    def test_scan_state_contract_without_frames(self):
        response = self.client.get("/api/v1/scan/state")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for key in (
            "sequence",
            "state",
            "hint",
            "detections",
            "processing",
            "camera_available",
            "error",
        ):
            self.assertIn(key, body)
        self.assertEqual(body["detections"], [])

    def test_scan_select_requires_a_live_detection(self):
        response = self.client.post("/api/v1/scan/select", json={"index": 0})
        self.assertEqual(response.status_code, 422)
        problem = response.json()
        self.assertEqual(problem["code"], "invalid_request")
        self.assertEqual(problem["status"], 422)

    def test_scan_select_rejects_negative_index(self):
        response = self.client.post("/api/v1/scan/select", json={"index": -1})
        self.assertEqual(response.status_code, 422)

    def test_scan_command_endpoints_acknowledge(self):
        for path in (
            "/api/v1/scan/manual-capture",
            "/api/v1/scan/retake",
            "/api/v1/scan/cancel",
        ):
            response = self.client.post(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertTrue(response.json()["ok"])

    def test_fallback_upload_rejects_non_images(self):
        response = self.client.post(
            "/api/v1/scan/fallback",
            files={"file": ("notes.txt", b"not an image", "text/plain")},
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "invalid_request")

    def test_fallback_upload_accepts_decodable_image(self):
        import cv2
        import numpy as np

        image = np.full((48, 64, 3), 120, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        response = self.client.post(
            "/api/v1/scan/fallback",
            files={"file": ("photo.jpg", encoded.tobytes(), "image/jpeg")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        cleared = self.client.post("/api/v1/scan/fallback/clear")
        self.assertEqual(cleared.status_code, 200)

    def test_library_list_contract_is_demo_only(self):
        response = self.client.get("/api/v1/library/records")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["is_demo_only"])
        self.assertEqual(body["records"], [])
        self.assertEqual(body["total"], 0)

    def test_library_save_requires_an_accepted_result(self):
        response = self.client.post("/api/v1/library/records")
        self.assertEqual(response.status_code, 422)
        self.assertIn("no accepted crop", response.json()["detail"])

    def test_library_delete_requires_confirmation(self):
        response = self.client.delete("/api/v1/library/records/does-not-exist")
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "invalid_request")

    def test_library_delete_missing_record_is_not_found(self):
        response = self.client.delete("/api/v1/library/records/does-not-exist?confirmed=true")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "not_found")

    def test_problem_detail_schema_is_stable(self):
        response = self.client.delete("/api/v1/library/records/x?confirmed=true")
        problem = response.json()
        self.assertEqual(
            sorted(problem.keys()),
            ["code", "detail", "request_id", "status", "title", "type"],
        )

    def test_validation_error_carries_request_id_header(self):
        response = self.client.post("/api/v1/scan/select", json={"index": -1})
        self.assertIn("x-request-id", response.headers)

    def test_diagnostics_logs_are_bounded_and_structured(self):
        self.client.get("/api/v1/health/live")
        response = self.client.get("/api/v1/diagnostics/logs")
        self.assertEqual(response.status_code, 200)
        entries = response.json()
        self.assertIsInstance(entries, list)
        for entry in entries:
            self.assertEqual(
                sorted(entry.keys()),
                ["duration_ms", "logged_at", "method", "path", "request_id", "status"],
            )

    def test_frontend_is_served_from_the_api_origin(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Botanika", response.text)


class Phase6ApiContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.root = root
        settings = AppSettings(
            database_path=root / "database" / "phase6.sqlite",
            discoveries_dir=root / "media" / "discoveries",
            temp_crops_dir=root / "media" / "temp",
            backup_dir=root / "backups",
        )
        patcher = mock.patch.multiple(
            "botanika.vision.services.scan.ScanService",
            start=mock.DEFAULT,
            stop=mock.DEFAULT,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = create_app(settings)
        self.client = AsgiTestClient(self.app)
        self.addCleanup(self.client.close)

    def test_normal_runtime_uses_real_catalog_services_without_stub_mode(self):
        capabilities = self.client.get("/api/v1/capabilities").json()
        self.assertFalse(capabilities["classifier"]["available"])
        self.assertEqual(
            capabilities["classifier"]["model"]["version"],
            "india-starter-feature-1.0.0",
        )
        self.assertFalse(capabilities["classifier"]["model"]["deployment_ready"])
        self.assertIn("incomplete", capabilities["classifier"]["detail"].lower())
        self.assertTrue(capabilities["knowledge"]["available"])
        self.assertFalse(self.app.state.runtime.scan.classifier_stub)

        library = self.client.get("/api/v1/library/records").json()
        self.assertFalse(library["is_demo_only"])
        self.assertEqual(library["species_count"], 0)

    def test_species_and_chat_return_exact_non_root_citations(self):
        species = self.client.get("/api/v1/species").json()
        self.assertEqual(species["total"], 7)
        urls = [
            source["url"]
            for item in species["species"]
            for source in item["sources"]
            if source["source_type"] != "image-reference"
        ]
        self.assertTrue(urls)
        self.assertNotIn("https://powo.science.kew.org/", urls)
        self.assertNotIn("https://www.iucnredlist.org/", urls)

        chat = self.client.post(
            "/api/v1/chat",
            json={"question": "Where is the banyan native?"},
        ).json()
        self.assertFalse(chat["abstained"])
        self.assertIn("/taxon/", chat["citations"][0]["source"]["url"])

    def test_restore_route_reseeds_current_catalog_knowledge(self):
        archive = self.app.state.runtime.library.export_archive(self.root / "empty-backup.zip")
        response = self.client.post(
            "/api/v1/library/restore?confirmed=true",
            files={"file": ("empty-backup.zip", archive.read_bytes(), "application/zip")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        search = self.client.get(
            "/api/v1/knowledge/search?q=native&species_id=in%3Aocimum-tenuiflorum"
        ).json()
        self.assertEqual(len(search["hits"]), 1)
        self.assertIn("/taxon/", search["hits"][0]["source"]["url"])


if __name__ == "__main__":
    unittest.main()
