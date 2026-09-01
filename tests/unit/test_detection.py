from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

import numpy as np

from botanika.vision.detection import (
    BoundingBox,
    DetectorMetrics,
    DetectorLoadError,
    LetterboxTransform,
    ModelManifest,
    YoloOnnxDetector,
    fit_frame_to_window,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_MANIFEST_PATH = PROJECT_ROOT / "config" / "models" / "yolo11n-coco.json"
MODEL_ARTIFACT_PATH = PROJECT_ROOT / "models" / "detectors" / "yolo11n.onnx"


class FakeSession:
    def __init__(self, output: np.ndarray):
        self.output = output
        self.feed: dict[str, np.ndarray] | None = None

    def get_inputs(self):
        return [SimpleNamespace(name="images")]

    def get_outputs(self):
        return [SimpleNamespace(name="output0")]

    def run(self, output_names, input_feed):
        self.feed = input_feed
        return [self.output]


def make_manifest(directory: Path, artifact: Path, *, labels: list[str]) -> ModelManifest:
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    path = directory / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "model_name": "test-yolo",
                "version": "test-1",
                "artifact": artifact.name,
                "source": "test://fixture",
                "license": "test-license",
                "sha256": digest,
                "input_size": [640, 640],
                "labels": labels,
            }
        ),
        encoding="utf-8",
    )
    return ModelManifest.from_file(path)


class DetectionTests(unittest.TestCase):
    def test_letterbox_round_trip_restores_source_coordinates(self):
        transform = LetterboxTransform.for_image(200, 100, 640, 640)
        source_box = BoundingBox(25, 37.5, 75, 62.5)

        restored = transform.to_source_box(transform.to_input_box(source_box))

        self.assertAlmostEqual(restored.x1, source_box.x1)
        self.assertAlmostEqual(restored.y1, source_box.y1)
        self.assertAlmostEqual(restored.x2, source_box.x2)
        self.assertAlmostEqual(restored.y2, source_box.y2)
        self.assertEqual(transform.pad_top, 160)

    def test_display_transform_letterboxes_without_distorting_boxes(self):
        frame = np.zeros((864, 1536, 3), dtype=np.uint8)

        canvas, transform = fit_frame_to_window(frame, 800, 480)
        display_box = transform.to_display_box(BoundingBox(0, 0, 1536, 864))

        self.assertEqual(canvas.shape, (480, 800, 3))
        self.assertEqual((transform.rendered_width, transform.rendered_height), (800, 450))
        self.assertEqual((transform.offset_x, transform.offset_y), (0, 15))
        self.assertAlmostEqual(display_box.x1, 0)
        self.assertAlmostEqual(display_box.y1, 15)
        self.assertAlmostEqual(display_box.x2, 800)
        self.assertAlmostEqual(display_box.y2, 465)

    def test_yolo_output_is_nms_filtered_and_mapped_to_source(self):
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            artifact = directory / "model.onnx"
            artifact.write_bytes(b"test model")
            manifest = make_manifest(directory, artifact, labels=["plant", "person"])
            # YOLO11 output is [batch, features, anchors]: 4 box values + 2 scores.
            output = np.zeros((1, 6, 10), dtype=np.float32)
            output[0, :4, 0] = [320, 320, 160, 80]
            output[0, 4:, 0] = [0.90, 0.10]
            output[0, :4, 1] = [322, 322, 160, 80]
            output[0, 4:, 1] = [0.80, 0.10]
            output[0, :4, 2] = [500, 320, 80, 80]
            output[0, 4:, 2] = [0.10, 0.75]
            fake_session = FakeSession(output)
            detector = YoloOnnxDetector(
                manifest,
                confidence_threshold=0.25,
                session_factory=lambda _: fake_session,
            )

            detector.load()
            detections = detector.detect(np.zeros((100, 200, 3), dtype=np.uint8))

            self.assertEqual(len(detections), 2)
            self.assertEqual([detection.label for detection in detections], ["plant", "person"])
            self.assertAlmostEqual(detections[0].confidence, 0.90)
            self.assertAlmostEqual(detections[0].box.x1, 75.0)
            self.assertAlmostEqual(detections[0].box.y1, 37.5)
            self.assertIsNotNone(fake_session.feed)
            self.assertEqual(fake_session.feed["images"].shape, (1, 3, 640, 640))
            self.assertEqual(detector.metrics.p50_ms, detector.metrics.p95_ms)

    def test_checksum_mismatch_is_rejected_before_session_load(self):
        with TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            artifact = directory / "model.onnx"
            artifact.write_bytes(b"test model")
            manifest_path = directory / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "model_name": "test-yolo",
                        "version": "test-1",
                        "artifact": artifact.name,
                        "source": "test://fixture",
                        "license": "test-license",
                        "sha256": "0" * 64,
                        "labels": ["plant"],
                    }
                ),
                encoding="utf-8",
            )
            detector = YoloOnnxDetector(ModelManifest.from_file(manifest_path))

            with self.assertRaisesRegex(DetectorLoadError, "checksum mismatch"):
                detector.load()

    def test_metrics_are_bounded_and_report_percentiles(self):
        metrics = DetectorMetrics(max_samples=3)
        for latency in (10, 20, 30, 40):
            metrics.record(latency)

        self.assertEqual(metrics.latencies_ms, [20.0, 30.0, 40.0])
        self.assertEqual(metrics.p50_ms, 30.0)
        self.assertEqual(metrics.p95_ms, 40.0)

    @unittest.skipUnless(
        MODEL_MANIFEST_PATH.is_file() and MODEL_ARTIFACT_PATH.is_file(),
        "bundled YOLO11n runtime artifact is not present",
    )
    def test_bundled_yolo_manifest_runs_synthetic_image_smoke(self):
        manifest = ModelManifest.from_file(MODEL_MANIFEST_PATH)
        detector = YoloOnnxDetector(manifest)
        try:
            detector.load()
            detections = detector.detect(np.zeros((480, 800, 3), dtype=np.uint8))
        finally:
            detector.close()

        self.assertIsInstance(detections, list)
        self.assertGreaterEqual(len(detector.metrics.latencies_ms), 1)
        self.assertFalse(detector.is_loaded)


if __name__ == "__main__":
    unittest.main()
