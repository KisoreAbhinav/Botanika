from __future__ import annotations

import numpy as np
import unittest

from botanika.hardware.camera import (
    CameraConfig,
    CameraOpenError,
    CameraOwner,
    FrameReadError,
    convert_rgb_to_bgr,
)


class FakeCamera:
    def __init__(self, frames: list[object] | None = None, *, fail_start: bool = False):
        self.frames = list(frames or [])
        self.fail_start = fail_start
        self.calls: list[object] = []
        self.closed = False

    def create_preview_configuration(self, **kwargs):
        self.calls.append(("create_preview_configuration", kwargs))
        return kwargs

    def configure(self, configuration):
        self.calls.append(("configure", configuration))

    def start(self):
        self.calls.append("start")
        if self.fail_start:
            raise RuntimeError("camera busy")

    def capture_array(self, name="main"):
        self.calls.append(("capture_array", name))
        if not self.frames:
            raise RuntimeError("no more frames")
        frame = self.frames.pop(0)
        if isinstance(frame, BaseException):
            raise frame
        return frame

    def stop(self):
        self.calls.append("stop")

    def close(self):
        self.calls.append("close")
        self.closed = True


class CameraOwnerTests(unittest.TestCase):
    def test_rgb888_is_converted_to_bgr_without_changing_shape(self):
        rgb = np.array([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8)

        bgr = convert_rgb_to_bgr(rgb)

        self.assertEqual(bgr.tolist(), [[[30, 20, 10], [60, 50, 40]]])
        self.assertEqual(bgr.shape, rgb.shape)

    def test_invalid_frame_shape_is_rejected(self):
        with self.assertRaisesRegex(FrameReadError, "unexpected frame shape"):
            convert_rgb_to_bgr(np.zeros((4, 4), dtype=np.uint8))

    def test_camera_config_has_measured_preview_defaults(self):
        config = CameraConfig()

        self.assertEqual(
            config.main_stream, {"size": (1536, 864), "format": "RGB888"}
        )
        self.assertEqual(config.preview_configuration()["controls"], {"FrameRate": 30.0})

    def test_owner_opens_reads_sequential_frames_and_closes(self):
        fake = FakeCamera([np.array([[[1, 2, 3]]], dtype=np.uint8)])
        owner = CameraOwner(camera_factory=lambda: fake, clock=lambda: 12.5)

        owner.open()
        result = owner.read()
        owner.close()

        self.assertFalse(owner.is_running)
        self.assertEqual(result.sequence, 1)
        self.assertEqual(result.captured_at, 12.5)
        self.assertEqual(result.image.tolist(), [[[3, 2, 1]]])
        self.assertEqual(owner.frames_read, 1)
        self.assertEqual(owner.dropped_frames, 0)
        self.assertTrue(fake.closed)
        self.assertIn("start", fake.calls)
        self.assertEqual(fake.calls[-2:], ["stop", "close"])

    def test_frame_read_failure_counts_as_dropped_and_can_be_retried(self):
        fake = FakeCamera(
            [RuntimeError("transient read error"), np.zeros((1, 1, 3), dtype=np.uint8)]
        )
        owner = CameraOwner(camera_factory=lambda: fake)
        owner.open()

        with self.assertRaisesRegex(FrameReadError, "could not read"):
            owner.read()
        result = owner.read()
        owner.close()

        self.assertEqual(result.sequence, 1)
        self.assertEqual(owner.frames_read, 1)
        self.assertEqual(owner.dropped_frames, 1)

    def test_start_failure_closes_a_partially_opened_camera(self):
        fake = FakeCamera(fail_start=True)
        owner = CameraOwner(camera_factory=lambda: fake)

        with self.assertRaisesRegex(CameraOpenError, "camera busy"):
            owner.open()

        self.assertTrue(fake.closed)
        self.assertEqual(fake.calls[-2:], ["stop", "close"])
        self.assertFalse(owner.is_running)


if __name__ == "__main__":
    unittest.main()
