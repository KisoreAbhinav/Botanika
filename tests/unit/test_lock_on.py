from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import cv2
import numpy as np

from botanika.vision.detection import BoundingBox, Detection
from botanika.vision.quality import (
    CropStore,
    LockOnConfig,
    LockOnEngine,
    LockOnState,
    QualityConfig,
    evaluate_crop,
    select_candidate,
)


def detection(
    box: tuple[float, float, float, float],
    *,
    label: str = "potted plant",
    class_id: int = 58,
    confidence: float = 0.9,
) -> Detection:
    return Detection(class_id, label, confidence, BoundingBox(*box))


def sharp_frame(height: int = 300, width: int = 400) -> np.ndarray:
    rng = np.random.default_rng(42)
    return rng.integers(20, 235, size=(height, width, 3), dtype=np.uint8)


def test_quality_config() -> QualityConfig:
    return QualityConfig(
        min_target_width=20,
        min_target_height=20,
        min_laplacian_variance=1,
        min_mean_luma=1,
        max_mean_luma=254,
        max_saturated_fraction=1,
        edge_margin_ratio=0,
    )


class LockOnTests(unittest.TestCase):
    def test_select_candidate_prefers_largest_eligible_box(self):
        candidates = [
            detection((10, 10, 290, 290)),
            detection((150, 100, 250, 200)),
            detection((20, 20, 280, 280), label="person", class_id=0),
        ]

        selected = select_candidate(candidates, 300, 300, frozenset({"potted plant"}))

        self.assertIsNotNone(selected)
        self.assertEqual(selected.box, BoundingBox(10, 10, 290, 290))

    def test_stable_sharp_target_captures_exactly_one_crop(self):
        frame = sharp_frame()
        target = detection((80, 60, 240, 220))
        with TemporaryDirectory() as temp_dir:
            store = CropStore(Path(temp_dir), padding_ratio=0)
            engine = LockOnEngine(
                LockOnConfig(
                    stable_checks=3,
                    cooldown_frames=2,
                    crop_padding_ratio=0,
                    quality=test_quality_config(),
                ),
                store,
            )

            first = engine.update(frame, [target])
            second = engine.update(frame, [target])
            third = engine.update(frame, [target])

            self.assertEqual(first.state, LockOnState.TRACKING)
            self.assertEqual(second.state, LockOnState.HOLD_STEADY)
            self.assertEqual(third.state, LockOnState.CAPTURED)
            self.assertIsNotNone(third.capture)
            self.assertIsNotNone(third.capture.path)
            files = list(Path(temp_dir).glob("*.png"))
            self.assertEqual(len(files), 1)
            saved = cv2.imread(str(files[0]))
            self.assertEqual(saved.shape[:2], (160, 160))
            self.assertNotEqual(saved.shape[:2], frame.shape[:2])

            engine.update(frame, [target])
            engine.update(frame, [target])
            engine.update(frame, [target])
            self.assertEqual(len(list(Path(temp_dir).glob("*.png"))), 1)

    def test_moving_target_never_auto_captures(self):
        frame = sharp_frame()
        boxes = [
            (80, 60, 240, 220),
            (145, 60, 305, 220),
            (80, 60, 240, 220),
            (145, 60, 305, 220),
            (80, 60, 240, 220),
        ]
        with TemporaryDirectory() as temp_dir:
            store = CropStore(Path(temp_dir), padding_ratio=0)
            engine = LockOnEngine(
                LockOnConfig(stable_checks=3, crop_padding_ratio=0, quality=test_quality_config()),
                store,
            )

            updates = [engine.update(frame, [detection(box)]) for box in boxes]

            self.assertTrue(all(update.capture is None for update in updates))
            self.assertFalse(list(Path(temp_dir).glob("*.png")))
            self.assertEqual(updates[-1].state, LockOnState.TRACKING)

    def test_blurry_target_is_rejected_after_stability(self):
        frame = np.full((300, 400, 3), 128, dtype=np.uint8)
        target = detection((80, 60, 240, 220))
        with TemporaryDirectory() as temp_dir:
            engine = LockOnEngine(
                LockOnConfig(stable_checks=3, crop_padding_ratio=0, quality=test_quality_config()),
                CropStore(Path(temp_dir), padding_ratio=0),
            )

            engine.update(frame, [target])
            engine.update(frame, [target])
            update = engine.update(frame, [target])

            self.assertEqual(update.state, LockOnState.CHECKING_SHARPNESS)
            self.assertIn("blurry", update.quality.reasons)
            self.assertFalse(update.quality.ready)
            self.assertFalse(list(Path(temp_dir).glob("*.png")))

    def test_quality_rejects_small_dark_and_edge_clipped_crop(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)

        result = evaluate_crop(
            frame[:10, :10],
            BoundingBox(0, 0, 10, 10),
            100,
            100,
            QualityConfig(min_target_width=20, min_target_height=20, min_laplacian_variance=1),
        )

        self.assertFalse(result.ready)
        self.assertIn("target too small", result.reasons)
        self.assertIn("target touches frame edge", result.reasons)
        self.assertIn("too dark", result.reasons)
        self.assertIn("blurry", result.reasons)

    def test_crop_store_deduplicates_rapid_identical_saves(self):
        frame = sharp_frame()
        box = BoundingBox(80, 60, 240, 220)
        with TemporaryDirectory() as temp_dir:
            store = CropStore(Path(temp_dir), padding_ratio=0, deduplication_seconds=5)

            first = store.save(frame, box)
            second = store.save(frame, box)

            self.assertIsNotNone(first.path)
            self.assertTrue(second.duplicate)
            self.assertIsNone(second.path)
            self.assertEqual(len(list(Path(temp_dir).glob("*.png"))), 1)


if __name__ == "__main__":
    unittest.main()
