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


class ProductionStaticMountTest(unittest.TestCase):
    """The production app must not write compatibility data into the checkout."""

    def test_create_app_does_not_create_legacy_demo_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            demo_dir = root / "checkout" / "data" / "media" / "discoveries" / "demo"
            settings = AppSettings(
                database_path=root / "runtime" / "database.sqlite",
                discoveries_dir=root / "runtime" / "discoveries",
                demo_discoveries_dir=demo_dir,
            )

            create_app(settings)

            self.assertFalse(demo_dir.exists())


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
        self.remote = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app, client=("192.168.50.20", 41000)),
            base_url="http://192.168.50.1",
        )
        self.stranger = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app, client=("192.168.50.21", 41001)),
            base_url="http://192.168.50.1",
        )

    def get(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.client.get(path, **kwargs))

    def post(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.client.post(path, **kwargs))

    def delete(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.client.delete(path, **kwargs))

    def patch(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.client.patch(path, **kwargs))

    def remote_get(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.remote.get(path, **kwargs))

    def remote_post(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.remote.post(path, **kwargs))

    def stranger_get(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.stranger.get(path, **kwargs))

    def stranger_post(self, path: str, **kwargs):
        return self.loop.run_until_complete(self.stranger.post(path, **kwargs))

    def close(self) -> None:
        self.loop.run_until_complete(self.stranger.aclose())
        self.loop.run_until_complete(self.remote.aclose())
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

    def test_phase7_network_status_and_landing_page_are_same_origin(self):
        status = self.client.get("/api/v1/network/status")
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertEqual(body["status"]["state"], "disabled")
        self.assertEqual(body["configuration"]["hostname"], "botanika.home.arpa")

        capabilities = self.client.get("/api/v1/capabilities").json()
        self.assertIn("network", capabilities)
        self.assertFalse(capabilities["network"]["available"])

        landing = self.client.get("/connect")
        self.assertEqual(landing.status_code, 200)
        self.assertIn("SOLO mode is active", landing.text)
        self.assertIn("Open Botanika", landing.text)

    def test_phase8_mode_pairing_single_controller_and_crop_only_upload(self):
        solo = self.client.get("/api/v1/mode/status")
        self.assertEqual(solo.status_code, 200)
        self.assertEqual(solo.json()["mode"], "SOLO")

        self.assertEqual(solo.json()["client_role"], "operator")
        self.assertEqual(
            self.client.remote_get("/api/v1/library/records").status_code,
            401,
        )
        self.assertEqual(
            self.client.remote_post("/api/v1/mode/toggle").status_code,
            401,
        )

        unpaired = self.client.post("/api/v1/mode/toggle")
        self.assertEqual(unpaired.status_code, 200)
        unpaired_body = unpaired.json()
        self.assertEqual(unpaired_body["mode"], "NETWORKED_UNPAIRED")
        code = unpaired_body["pairing"]["code"]

        remote_status = self.client.remote_get("/api/v1/mode/status")
        self.assertEqual(remote_status.status_code, 200)
        self.assertEqual(remote_status.json()["client_role"], "remote")
        self.assertNotIn("code", remote_status.json()["pairing"])
        self.assertIsNone(remote_status.json()["pairing_code"])
        remote_landing = self.client.remote_get("/connect")
        self.assertNotIn(code, remote_landing.text)
        self.assertEqual(
            self.client.remote_post("/api/v1/mode/takeover").status_code,
            401,
        )

        paired = self.client.remote_post(
            "/api/v1/mode/pair",
            json={"code": code, "device_name": "Test phone", "client_id": "test-client"},
        )
        self.assertEqual(paired.status_code, 200)
        token = paired.json()["session_token"]
        self.assertEqual(paired.json()["status"]["controller_count"], 1)
        self.assertNotIn("session_token", paired.json()["status"])
        self.assertEqual(
            self.client.remote_post("/api/v1/mode/takeover").status_code,
            401,
        )
        self.assertEqual(
            self.client.remote_post("/api/v1/scan/manual-capture").status_code,
            401,
        )
        self.assertEqual(
            self.client.stranger_get("/api/v1/library/records").status_code,
            401,
        )
        self.assertEqual(
            self.client.remote_get("/api/v1/library/records").status_code,
            200,
        )

        second = self.client.post(
            "/api/v1/mode/pair",
            json={"code": code, "device_name": "Second phone"},
        )
        self.assertEqual(second.status_code, 422)
        self.assertIn("another controller", second.json()["detail"])

        unauthorized = self.client.post(
            "/api/v1/mode/controller/crop",
            files={"file": ("crop.png", b"not an image", "image/png")},
        )
        self.assertEqual(unauthorized.status_code, 401)

        import cv2
        import hashlib
        import numpy as np

        image = np.full((48, 64, 3), 120, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        payload = encoded.tobytes()
        crop = self.client.remote_post(
            "/api/v1/mode/controller/crop",
            files={"file": ("crop.png", payload, "image/png")},
            data={
                "crop_hash": hashlib.sha256(payload).hexdigest(),
                "width": "64",
                "height": "48",
                "client_request_id": "integration-crop",
            },
        )
        self.assertEqual(crop.status_code, 200)
        self.assertEqual(crop.json()["crop"]["sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(crop.json()["crop"]["width"], 64)
        self.assertEqual(crop.json()["crop"]["height"], 48)
        self.assertEqual(crop.json()["request_id"], "integration-crop")

        mismatch = self.client.remote_post(
            "/api/v1/mode/controller/crop",
            files={"file": ("crop.png", payload, "image/png")},
            data={"crop_hash": "0" * 64},
        )
        self.assertEqual(mismatch.status_code, 422)
        self.assertIn("hash", mismatch.json()["detail"])

        classification = crop.json()["classification"]
        self.assertEqual(classification["result"]["status"], "accepted")
        stale_save = self.client.remote_post(
            "/api/v1/library/records",
            json={"request_id": "wrong-request", "crop_hash": classification["crop_hash"]},
        )
        self.assertEqual(stale_save.status_code, 422)
        saved = self.client.remote_post(
            "/api/v1/library/records",
            json={
                "request_id": classification["request_id"],
                "crop_hash": classification["crop_hash"],
                "position": {
                    "latitude": 19.076,
                    "longitude": 72.8777,
                    "accuracy_m": 12.0,
                    "timestamp": 1788364800.0,
                    "source": "paired-browser-geolocation",
                },
            },
        )
        self.assertEqual(saved.status_code, 200)
        crop_url = saved.json()["record"]["crop_url"]
        self.assertEqual(self.client.remote_get(crop_url).status_code, 200)
        self.assertEqual(self.client.stranger_get(crop_url).status_code, 401)

        second_image = np.full((48, 64, 3), 150, dtype=np.uint8)
        second_ok, second_encoded = cv2.imencode(".png", second_image)
        self.assertTrue(second_ok)
        second_payload = second_encoded.tobytes()
        second_crop = self.client.remote_post(
            "/api/v1/mode/controller/crop",
            files={"file": ("crop.png", second_payload, "image/png")},
            data={
                "crop_hash": hashlib.sha256(second_payload).hexdigest(),
                "width": "64",
                "height": "48",
                "client_request_id": "integration-crop-2",
            },
        )
        self.assertEqual(second_crop.status_code, 200)
        second_classification = second_crop.json()["classification"]
        second_save = self.client.remote_post(
            "/api/v1/library/records",
            json={
                "request_id": second_classification["request_id"],
                "crop_hash": second_classification["crop_hash"],
            },
        )
        self.assertEqual(second_save.status_code, 200)
        self.assertEqual(self.client.remote_get("/api/v1/library/records").json()["total"], 2)

        disconnected = self.client.remote_post(
            "/api/v1/mode/disconnect",
        )
        self.assertEqual(disconnected.status_code, 200)
        self.assertEqual(disconnected.json()["mode"], "NETWORKED_UNPAIRED")
        self.assertNotIn("code", disconnected.json()["pairing"])
        second_code = self.client.get("/api/v1/mode/status").json()["pairing"]["code"]
        paired_again = self.client.remote_post(
            "/api/v1/mode/pair",
            json={"code": second_code, "device_name": "Second phone"},
        )
        self.assertEqual(paired_again.status_code, 200)
        takeover = self.client.post("/api/v1/mode/takeover")
        self.assertEqual(takeover.status_code, 200)
        self.assertEqual(takeover.json()["mode"], "NETWORKED_UNPAIRED")
        stale_heartbeat = self.client.post(
            "/api/v1/mode/heartbeat",
            headers={"X-Botanika-Controller-Token": paired_again.json()["session_token"]},
        )
        self.assertEqual(stale_heartbeat.status_code, 401)

        solo = self.client.post("/api/v1/mode/solo")
        self.assertEqual(solo.status_code, 200)
        self.assertEqual(solo.json()["mode"], "SOLO")

    def test_cloudflare_proxy_headers_keep_tunnel_callers_remote(self):
        # ASGITransport's default peer is loopback, matching cloudflared's
        # local hop. Valid Cloudflare markers must still make this remote:
        # status redacts the invitation and operator POSTs fail. The paired
        # data/classifier calls below model a phone on a different network;
        # cloudflared is not started inside this deterministic ASGI test.
        self.assertEqual(self.client.post("/api/v1/mode/toggle").status_code, 200)
        headers = {
            "CF-Connecting-IP": "198.51.100.22",
            "CF-Ray": "0123456789abcdef-SJC",
        }
        status = self.client.get("/api/v1/mode/status", headers=headers)
        self.assertEqual(status.status_code, 200)
        body = status.json()
        self.assertEqual(body["client_role"], "remote")
        self.assertNotIn("code", body["pairing"])
        self.assertIsNone(body["pairing_code"])
        takeover = self.client.post("/api/v1/mode/takeover", headers=headers)
        self.assertEqual(takeover.status_code, 401)
        network = self.client.get("/api/v1/network/status", headers=headers)
        self.assertEqual(network.status_code, 401)

        code = self.client.get("/api/v1/mode/status").json()["pairing"]["code"]
        paired = self.client.post(
            "/api/v1/mode/pair",
            headers=headers,
            json={"code": code, "device_name": "Internet phone", "client_id": "wan-phone"},
        )
        self.assertEqual(paired.status_code, 200)
        token = paired.json()["session_token"]
        controller_headers = {
            **headers,
            "X-Botanika-Controller-Token": token,
        }
        # A loopback peer plus Cloudflare markers must not be treated as the
        # Pi operator, while the active paired lease can read Pi-owned data.
        self.assertEqual(
            self.client.get("/api/v1/library/records", headers=controller_headers).status_code,
            200,
        )
        self.assertEqual(
            self.client.get("/api/v1/weeds/runs", headers=controller_headers).status_code,
            200,
        )
        export = self.client.get("/api/v1/weeds/export", headers=controller_headers)
        self.assertEqual(export.status_code, 200)
        self.assertIn("attachment", export.headers.get("content-disposition", ""))
        self.assertTrue(export.json()["coordinate_only"])
        self.assertNotIn("frame_data_url", export.text)
        self.assertEqual(
            self.client.stranger_get("/api/v1/weeds/runs", headers=headers).status_code,
            401,
        )
        # The same origin serves the classifier endpoint through the tunnel;
        # this crop is intentionally a bounded still, not a live stream.
        import cv2
        import hashlib
        import numpy as np

        image = np.full((24, 32, 3), 120, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", image)
        self.assertTrue(ok)
        payload = encoded.tobytes()
        crop = self.client.post(
            "/api/v1/mode/controller/crop",
            headers=controller_headers,
            files={"file": ("sample.png", payload, "image/png")},
            data={
                "crop_hash": hashlib.sha256(payload).hexdigest(),
                "width": "32",
                "height": "24",
                "client_request_id": "wan-crop",
            },
        )
        self.assertEqual(crop.status_code, 200)
        self.assertEqual(crop.json()["request_id"], "wan-crop")


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
