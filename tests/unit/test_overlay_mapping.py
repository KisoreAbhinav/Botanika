"""Phase 5 overlay/crop coordinate tests across source aspect ratios.

The kiosk draws boxes from the transform published with every preview event.
These tests pin the letterbox math for wide, tall, square, and odd sources so
the browser overlay stays exact regardless of camera geometry.
"""

from __future__ import annotations

import unittest

from botanika.vision.services.overlay import OverlayTransform


class Box:
    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2


class TestOverlayTransform(unittest.TestCase):
    PREVIEW = (500, 330)

    def assertContainFit(self, source_width: int, source_height: int) -> OverlayTransform:
        transform = OverlayTransform.for_frame(source_width, source_height, *self.PREVIEW)
        self.assertEqual(transform.preview_width, self.PREVIEW[0])
        self.assertEqual(transform.preview_height, self.PREVIEW[1])
        expected_scale = min(
            self.PREVIEW[0] / source_width, self.PREVIEW[1] / source_height
        )
        self.assertAlmostEqual(transform.scale, expected_scale, places=9)
        # The rendered rectangle fits inside the canvas and is centred.
        self.assertLessEqual(transform.rendered_width, self.PREVIEW[0])
        self.assertLessEqual(transform.rendered_height, self.PREVIEW[1])
        self.assertEqual(
            (transform.preview_width - transform.rendered_width) // 2, transform.offset_x
        )
        self.assertEqual(
            (transform.preview_height - transform.rendered_height) // 2, transform.offset_y
        )
        return transform

    def test_wide_source_letterboxes_top_and_bottom(self):
        transform = self.assertContainFit(1280, 720)
        self.assertGreater(transform.offset_y, 0)
        self.assertEqual(transform.offset_x, 0)

    def test_tall_source_letterboxes_left_and_right(self):
        transform = self.assertContainFit(720, 1280)
        self.assertGreater(transform.offset_x, 0)
        self.assertEqual(transform.offset_y, 0)

    def test_square_source_letterboxes_left_and_right(self):
        transform = self.assertContainFit(1000, 1000)
        self.assertGreater(transform.offset_x, 0)

    def test_exact_aspect_ratio_has_no_letterbox(self):
        transform = self.assertContainFit(1000, 660)
        self.assertEqual(transform.offset_x, 0)
        self.assertEqual(transform.offset_y, 0)
        self.assertEqual(transform.rendered_width, self.PREVIEW[0])
        self.assertEqual(transform.rendered_height, self.PREVIEW[1])

    def test_box_mapping_uses_scale_and_offset(self):
        transform = self.assertContainFit(1280, 720)
        source_box = Box(100, 50, 300, 250)
        x1, y1, x2, y2 = transform.to_preview_box(source_box)
        self.assertAlmostEqual(x1, 100 * transform.scale + transform.offset_x)
        self.assertAlmostEqual(y1, 50 * transform.scale + transform.offset_y)
        self.assertAlmostEqual(x2, 300 * transform.scale + transform.offset_x)
        self.assertAlmostEqual(y2, 250 * transform.scale + transform.offset_y)

    def test_box_mapping_round_trips_corners(self):
        for source in ((1280, 720), (720, 1280), (1000, 1000), (640, 480)):
            transform = self.assertContainFit(*source)
            corners = [
                Box(0, 0, source[0], source[1]),
                Box(source[0] / 4, source[1] / 4, source[0] / 2, source[1] / 2),
            ]
            for corner in corners:
                x1, y1, x2, y2 = transform.to_preview_box(corner)
                self.assertGreaterEqual(x2, x1)
                self.assertGreaterEqual(y2, y1)
                clamped = transform.clamp_preview((x1, y1, x2, y2))
                self.assertGreaterEqual(clamped[0], 0)
                self.assertGreaterEqual(clamped[1], 0)
                self.assertLessEqual(clamped[2], self.PREVIEW[0])
                self.assertLessEqual(clamped[3], self.PREVIEW[1])

    def test_invalid_dimensions_are_rejected(self):
        for source in ((0, 100), (100, 0), (-5, 100)):
            with self.assertRaises(ValueError):
                OverlayTransform.for_frame(source[0], source[1], *self.PREVIEW)
        with self.assertRaises(ValueError):
            OverlayTransform.for_frame(100, 100, 0, 100)

    def test_clamping_keeps_boxes_inside_the_canvas(self):
        transform = self.assertContainFit(1280, 720)
        clamped = transform.clamp_preview((-10, -10, 9999, 9999))
        self.assertEqual(clamped, (0.0, 0.0, 500.0, 330.0))


if __name__ == "__main__":
    unittest.main()
