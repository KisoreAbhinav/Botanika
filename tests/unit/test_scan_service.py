from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from botanika.core.settings import AppSettings
from botanika.vision.classification import DummyClassifier, DummyScenario
from botanika.vision.detection import (
    BoundingBox,
    Detection,
    DetectorMetrics,
    DetectorUnavailable,
)
from botanika.vision.services import OverlayTransform, ScanService


def sharp_frame(width: int = 640, height: int = 480) -> np.ndarray:
    grid = np.indices((height, width)).sum(axis=0) % 2
    values = np.where(grid, 210, 40).astype(np.uint8)
    return np.repeat(values[:, :, None], 3, axis=2)


def wait_until(predicate, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.005)
    raise AssertionError("condition was not reached before timeout")


class FakeDetector:
    def __init__(self, *, stop_after: threading.Event | None = None) -> None:
        self.is_loaded = True
        self.metrics = DetectorMetrics()
        self.stop_after = stop_after

    def load(self) -> None:
        self.is_loaded = True

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if self.stop_after is not None and self.stop_after.is_set():
            return []
        return [
            Detection(
                class_id=58,
                label="potted plant",
                confidence=0.91,
                box=BoundingBox(160, 100, 480, 380),
            )
        ]


class FailingDetector(FakeDetector):
    def __init__(self) -> None:
        super().__init__()
        self.is_loaded = False

    def load(self) -> None:
        raise DetectorUnavailable("detector intentionally unavailable")


class NoPlantDetector(FakeDetector):
    """Generic detector fixture with no eligible COCO plant box."""

    def detect(self, frame: np.ndarray) -> list[Detection]:
        return [
            Detection(
                class_id=14,
                label="bird",
                confidence=0.93,
                box=BoundingBox(120, 80, 520, 400),
            )
        ]


class FakeCamera:
    active = 0
    max_active = 0

    def __init__(self, frame: np.ndarray, *, fail_start: bool = False) -> None:
        self.frame = frame
        self.fail_start = fail_start
        self.closed = False
        self.captures = 0
        self.started = False

    def create_preview_configuration(self, **kwargs):
        return kwargs

    def configure(self, configuration):
        return None

    def start(self):
        if self.fail_start:
            raise RuntimeError("camera busy")
        self.started = True
        FakeCamera.active += 1
        FakeCamera.max_active = max(FakeCamera.max_active, FakeCamera.active)

    def capture_array(self, name="main"):
        self.captures += 1
        time.sleep(0.002)
        return self.frame.copy()

    def stop(self):
        if self.started:
            self.started = False
            FakeCamera.active -= 1

    def close(self):
        self.closed = True


class BlockingClassifier:
    classifier_version = "blocking-test"
    is_stub = True

    def __init__(self) -> None:
        self.started = threading.Event()

    def classify(self, crop, *, cancellation=None):
        self.started.set()
        while cancellation is not None and not cancellation.is_cancelled:
            time.sleep(0.002)
        return DummyClassifier(scenario=DummyScenario.CANCELLED).classify(
            crop,
            cancellation=cancellation,
        )


class ScanServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.settings = AppSettings(
            stable_checks=2,
            cooldown_frames=2,
            temp_crops_dir=root / "crops",
            database_path=root / "library.sqlite",
            demo_discoveries_dir=root / "discoveries",
        )
        FakeCamera.active = 0
        FakeCamera.max_active = 0

    def test_normal_runtime_keeps_camera_owner_default_factory(self):
        service = ScanService(self.settings, detector=FakeDetector())
        with mock.patch("botanika.vision.services.scan.CameraOwner") as owner_type:
            owner = owner_type.return_value
            service._open_resources()

        owner_type.assert_called_once_with(
            config=mock.ANY,
            clock=mock.ANY,
        )
        owner.open.assert_called_once_with()

    def test_closed_camera_does_not_expose_a_stale_latest_frame(self):
        service = ScanService(self.settings, detector=FakeDetector())
        service._frame = sharp_frame()

        service._close_resources()

        self.assertIsNone(service.latest_frame())

    def test_preview_sequence_advances_for_each_camera_frame(self):
        service = ScanService(self.settings, detector=FakeDetector())
        image = sharp_frame(64, 48)
        service._frame = image
        transform = OverlayTransform.for_frame(64, 48, 500, 330)
        captured = SimpleNamespace(image=image, captured_at=1.0, sequence=1)

        service._publish_preview(captured, transform)
        first = service.latest_preview()
        captured.sequence = 2
        service._publish_preview(captured, transform)
        second = service.latest_preview()

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertGreater(second.sequence, first.sequence)
        self.assertEqual(second.source_sequence, 2)

    def test_result_remains_authoritative_until_retake_and_camera_has_one_owner(self):
        camera = FakeCamera(sharp_frame())
        service = ScanService(
            self.settings,
            camera_factory=lambda: camera,
            detector=FakeDetector(),
        )
        service.start()
        self.addCleanup(service.stop)

        result_snapshot = wait_until(
            lambda: (
                snapshot
                if (snapshot := service.latest_snapshot()) is not None
                and snapshot.classification is not None
                else None
            )
        )
        self.assertFalse(result_snapshot.processing)
        self.assertTrue(result_snapshot.classification.result.is_accepted)
        event_sequence = result_snapshot.sequence
        capture_count = camera.captures
        time.sleep(0.04)
        self.assertEqual(service.latest_snapshot().sequence, event_sequence)
        self.assertEqual(camera.captures, capture_count)

        service.request_retake()
        wait_until(lambda: service.latest_snapshot().sequence > event_sequence)
        service.stop()
        self.assertEqual(FakeCamera.max_active, 1)
        self.assertEqual(FakeCamera.active, 0)
        self.assertTrue(camera.closed)

    def test_processing_can_be_cancelled_cooperatively(self):
        classifier = BlockingClassifier()
        camera = FakeCamera(sharp_frame())
        detector = FakeDetector(stop_after=classifier.started)
        service = ScanService(
            self.settings,
            classifier=classifier,
            camera_factory=lambda: camera,
            detector=detector,
        )
        service.start()
        self.addCleanup(service.stop)
        wait_until(lambda: classifier.started.is_set())
        wait_until(lambda: service.latest_snapshot() and service.latest_snapshot().processing)

        event_sequence = service.events.last_sequence
        service.request_cancel()
        cancelled = wait_until(
            lambda: (
                next(
                    (
                        snapshot
                        for snapshot in service.events.after(event_sequence)
                        if snapshot.hint == "Scan cancelled"
                    ),
                    None,
                )
            )
        )
        self.assertFalse(cancelled.processing)
        self.assertIsNone(cancelled.classification)

    def test_fallback_publishes_image_and_works_without_detector(self):
        service = ScanService(self.settings, detector=FailingDetector())
        image = sharp_frame()
        service.set_fallback_image(image, "fixture.png")
        service._activate_pending_fallback()

        preview = service.latest_preview()
        snapshot = service.latest_snapshot()
        self.assertIsNotNone(preview)
        self.assertEqual(snapshot.mode, "fallback")
        self.assertEqual(snapshot.detections[0].label, "manual image")
        self.assertTrue(service.request_fallback_capture(0))
        service._run_fallback_capture(0)
        result = service.latest_snapshot()
        self.assertFalse(result.processing)
        self.assertTrue(result.classification.result.is_accepted)

    def test_manual_camera_capture_uses_central_roi_without_eligible_box(self):
        service = ScanService(self.settings, detector=NoPlantDetector())
        update = service._manual_frame_capture(sharp_frame())

        self.assertEqual(update.state.value, "Captured")
        self.assertEqual(update.detection.label, "manual central view")
        self.assertEqual(update.detection.class_id, -1)
        self.assertTrue(update.capture.manual)
        self.assertGreater(update.detection.box.x1, 0)
        self.assertGreater(update.detection.box.y1, 0)
        self.assertLess(update.detection.box.x2, 640)
        self.assertLess(update.detection.box.y2, 480)
        self.assertGreater(update.capture.width, 500)
        self.assertGreater(update.capture.height, 350)

    def test_manual_camera_hotkey_classifies_central_roi_when_detector_misses_tree(self):
        camera = FakeCamera(sharp_frame())
        service = ScanService(
            self.settings,
            camera_factory=lambda: camera,
            detector=NoPlantDetector(),
        )
        service.start()
        self.addCleanup(service.stop)
        service.request_manual_capture()

        result_snapshot = wait_until(
            lambda: (
                snapshot
                if (snapshot := service.latest_snapshot()) is not None
                and snapshot.classification is not None
                else None
            )
        )
        self.assertTrue(result_snapshot.classification.result.is_accepted)
        self.assertEqual(result_snapshot.detections[-1].label, "manual central view")
        self.assertEqual(result_snapshot.selected.label, "manual central view")
        self.assertTrue(result_snapshot.capture.manual)

    def test_camera_reconnect_closes_failed_owner_before_reopening(self):
        failed = FakeCamera(sharp_frame(), fail_start=True)
        recovered = FakeCamera(sharp_frame())
        cameras = iter((failed, recovered))
        service = ScanService(
            self.settings,
            camera_factory=lambda: next(cameras),
            detector=FakeDetector(),
        )
        service._retry_delay_seconds = 0.01
        service.start()
        self.addCleanup(service.stop)

        wait_until(lambda: service.camera_running)
        self.assertTrue(failed.closed)
        self.assertEqual(FakeCamera.max_active, 1)
        service.stop()
        self.assertTrue(recovered.closed)


if __name__ == "__main__":
    unittest.main()
