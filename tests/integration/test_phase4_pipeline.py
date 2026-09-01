from __future__ import annotations

import importlib.util
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.vision.classification import ClassificationPipeline, DummyClassifier
from botanika.vision.detection import BoundingBox, Detection, ModelManifest
from botanika.vision.quality import QualityConfig


MODULE_PATH = PROJECT_ROOT / "tools" / "run_lock_on.py"
SPEC = importlib.util.spec_from_file_location("run_lock_on_phase4", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
run_lock_on = importlib.util.module_from_spec(SPEC)
sys.modules["run_lock_on_phase4"] = run_lock_on
SPEC.loader.exec_module(run_lock_on)


class FakeCamera:
    def __init__(self, frame: np.ndarray) -> None:
        self.frame = frame
        self.closed = False

    def create_preview_configuration(self, **kwargs):
        return kwargs

    def configure(self, configuration):
        pass

    def start(self):
        pass

    def capture_array(self, name="main"):
        return self.frame.copy()

    def stop(self):
        pass

    def close(self):
        self.closed = True


class FakeDetector:
    def __init__(self, target: Detection) -> None:
        self.target = target
        self.closed = False

    def load(self):
        pass

    def detect(self, frame):
        return [self.target]

    def close(self):
        self.closed = True


class Phase4IntegrationTests(unittest.TestCase):
    def test_camera_detection_lock_crop_and_stub_classification_are_linked(self):
        frame = np.zeros((300, 400, 3), dtype=np.uint8)
        target_pixels = np.indices((160, 160)).sum(axis=0) % 2
        target = np.where(target_pixels[..., None] == 0, (40, 120, 220), (220, 120, 40))
        frame[60:220, 80:240] = target.astype(np.uint8)
        target = Detection(58, "potted plant", 0.95, BoundingBox(80, 60, 240, 220))
        fake_camera = FakeCamera(frame)
        fake_detector = FakeDetector(target)
        clock_values = count()
        classifier = DummyClassifier()
        pipeline = ClassificationPipeline(classifier, clock=lambda: next(clock_values) / 10)
        runs = []

        with TemporaryDirectory() as temp_dir:
            stats = run_lock_on.run_lock_on(
                run_lock_on.CameraConfig(width=400, height=300),
                ModelManifest(
                    manifest_path=Path(temp_dir) / "unused.json",
                    artifact_path=Path(temp_dir) / "unused.onnx",
                    model_name="unused",
                    version="test",
                    source="test://fixture",
                    license="test",
                    labels=("potted plant",),
                    sha256="0" * 64,
                ),
                QualityConfig(
                    min_target_width=20,
                    min_target_height=20,
                    min_laplacian_variance=1,
                    min_mean_luma=1,
                    max_mean_luma=254,
                    max_saturated_fraction=1,
                    edge_margin_ratio=0,
                ),
                Path(temp_dir) / "crops",
                stable_checks=3,
                padding=0,
                cooldown_frames=2,
                max_frames=6,
                headless=True,
                camera_factory=lambda: fake_camera,
                detector=fake_detector,
                clock=lambda: next(clock_values) / 10,
                on_capture=lambda item: runs.append(pipeline.classify_capture(item)),
            )

            self.assertEqual(stats.captures, 1)
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0].result.status.value, "accepted")
            self.assertTrue(runs[0].result.is_stub)
            self.assertEqual(runs[0].result.classifier_version, "stub-phase-4")
            self.assertEqual(runs[0].crop_path, runs[0].capture.path)
            self.assertTrue(runs[0].crop_path.is_file())

        self.assertTrue(fake_camera.closed)
        self.assertTrue(fake_detector.closed)


if __name__ == "__main__":
    unittest.main()
