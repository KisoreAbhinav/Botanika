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

    def test_select_candidate_uses_centrality_for_equal_size_targets(self):
        candidates = [
            detection((0, 0, 100, 100)),
            detection((150, 100, 250, 200)),
        ]

        selected = select_candidate(candidates, 400, 300, frozenset({"potted plant"}))

        self.assertIsNotNone(selected)
        self.assertEqual(selected.box, BoundingBox(150, 100, 250, 200))

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
            checking = engine.update(frame, [target])
            locked = engine.update(frame, [target])
            capturing = engine.update(frame, [target])
            captured = engine.update(frame, [target])

            self.assertEqual(first.state, LockOnState.TRACKING)
            self.assertEqual(second.state, LockOnState.HOLD_STEADY)
            self.assertEqual(checking.state, LockOnState.CHECKING_SHARPNESS)
            self.assertIsNone(checking.capture)
            self.assertEqual(locked.state, LockOnState.LOCKED)
            self.assertIsNone(locked.capture)
            self.assertEqual(capturing.state, LockOnState.CAPTURING)
            self.assertIsNone(capturing.capture)
            self.assertEqual(captured.state, LockOnState.CAPTURED)
            self.assertIsNotNone(captured.capture)
            self.assertIsNotNone(captured.capture.path)
            files = list(Path(temp_dir).glob("*.png"))
            self.assertEqual(len(files), 1)
            saved = cv2.imread(str(files[0]))
            self.assertEqual(saved.shape[:2], (160, 160))
            self.assertNotEqual(saved.shape[:2], frame.shape[:2])
            self.assertTrue(np.array_equal(saved, frame[60:220, 80:240]))

            cooldown_updates = [engine.update(frame, [target]) for _ in range(20)]
            self.assertEqual(len(list(Path(temp_dir).glob("*.png"))), 1)
            self.assertTrue(all(update.capture is None for update in cooldown_updates))
            self.assertTrue(all(update.state == LockOnState.COOLDOWN for update in cooldown_updates))

    def test_target_must_leave_before_automatic_capture_rearms(self):
        first_frame = sharp_frame()
        second_frame = first_frame.copy()
        second_frame[100:120, 100:120, 0] = np.clip(
            second_frame[100:120, 100:120, 0].astype(np.int16) + 20,
            0,
            255,
        ).astype(np.uint8)
        target = detection((80, 60, 240, 220))
        with TemporaryDirectory() as temp_dir:
            engine = LockOnEngine(
                LockOnConfig(
                    stable_checks=3,
                    cooldown_frames=1,
                    disappearance_tolerance=1,
                    quality=test_quality_config(),
                ),
                CropStore(Path(temp_dir), padding_ratio=0),
            )

            first_updates = [engine.update(first_frame, [target]) for _ in range(6)]
            same_target_updates = [
                engine.update(second_frame, [target]) for _ in range(12)
            ]
            absent_updates = [engine.update(second_frame, []) for _ in range(2)]
            second_updates = [engine.update(second_frame, [target]) for _ in range(6)]

            self.assertEqual(sum(update.capture is not None for update in first_updates), 1)
            self.assertTrue(all(update.capture is None for update in same_target_updates))
            self.assertEqual(absent_updates[-1].state, LockOnState.SEARCHING)
            self.assertEqual(sum(update.capture is not None for update in second_updates), 1)
            self.assertEqual(len(list(Path(temp_dir).glob("*.png"))), 2)

    def test_appearance_change_resets_stability_for_same_box(self):
        first_frame = sharp_frame()
        changed_frame = np.zeros_like(first_frame)
        changed_frame[:, :, 1] = np.indices(first_frame.shape[:2]).sum(axis=0) % 2 * 180 + 30
        target = detection((80, 60, 240, 220))
        with TemporaryDirectory() as temp_dir:
            engine = LockOnEngine(
                LockOnConfig(
                    stable_checks=3,
                    minimum_appearance_similarity=0.90,
                    quality=test_quality_config(),
                ),
                CropStore(Path(temp_dir), padding_ratio=0),
            )

            first = engine.update(first_frame, [target])
            changed = engine.update(changed_frame, [target])

            self.assertEqual(first.stable_checks, 1)
            self.assertEqual(changed.state, LockOnState.TRACKING)
            self.assertEqual(changed.stable_checks, 1)
            self.assertFalse(list(Path(temp_dir).glob("*.png")))

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
            checking = engine.update(frame, [target])
            update = engine.update(frame, [target])

            self.assertEqual(checking.state, LockOnState.CHECKING_SHARPNESS)
            self.assertIsNone(checking.quality)
            self.assertEqual(update.state, LockOnState.CHECKING_SHARPNESS)
            self.assertIn("blurry", update.quality.reasons)
            self.assertFalse(update.quality.ready)
            self.assertFalse(list(Path(temp_dir).glob("*.png")))

    def test_no_auto_capture_remains_locked_until_manual_capture(self):
        frame = sharp_frame()
        target = detection((80, 60, 240, 220))
        with TemporaryDirectory() as temp_dir:
            engine = LockOnEngine(
                LockOnConfig(
                    stable_checks=3,
                    automatic_capture=False,
                    quality=test_quality_config(),
                ),
                CropStore(Path(temp_dir), padding_ratio=0),
            )

            updates = [engine.update(frame, [target]) for _ in range(12)]

            self.assertEqual(updates[-1].state, LockOnState.LOCKED)
            self.assertTrue(all(update.capture is None for update in updates))
            self.assertFalse(list(Path(temp_dir).glob("*.png")))

            manual = engine.manual_capture(frame)
            self.assertEqual(manual.state, LockOnState.CAPTURED)
            self.assertTrue(manual.capture.manual)
            self.assertEqual(len(list(Path(temp_dir).glob("*.png"))), 1)

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

    def test_quality_rejects_bright_saturated_crop(self):
        frame = np.full((100, 100, 3), 255, dtype=np.uint8)

        result = evaluate_crop(
            frame[20:80, 20:80],
            BoundingBox(20, 20, 80, 80),
            100,
            100,
            QualityConfig(min_target_width=20, min_target_height=20),
        )

        self.assertFalse(result.ready)
        self.assertIn("too bright", result.reasons)
        self.assertIn("overexposed", result.reasons)

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
