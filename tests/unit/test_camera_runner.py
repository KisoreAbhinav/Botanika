from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "tools" / "run_camera.py"
SPEC = importlib.util.spec_from_file_location("run_camera", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
run_camera = importlib.util.module_from_spec(SPEC)
sys.modules["run_camera"] = run_camera
SPEC.loader.exec_module(run_camera)


class FakeCamera:
    def __init__(self):
        self.closed = False
        self.frames = [np.zeros((2, 2, 3), dtype=np.uint8) for _ in range(2)]

    def create_preview_configuration(self, **kwargs):
        return kwargs

    def configure(self, configuration):
        pass

    def start(self):
        pass

    def capture_array(self, name="main"):
        return self.frames.pop(0)

    def stop(self):
        pass

    def close(self):
        self.closed = True


class CameraRunnerTests(unittest.TestCase):
    def test_parser_uses_concrete_camera_defaults(self):
        args = run_camera.build_parser().parse_args([])

        config = run_camera.make_config(args)

        self.assertEqual(config, run_camera.DEFAULT_CONFIG)

    def test_headless_bounded_run_closes_camera(self):
        fake = FakeCamera()

        stats = run_camera.run_feed(
            run_camera.CameraConfig(width=2, height=2),
            max_frames=2,
            headless=True,
            camera_factory=lambda: fake,
            clock=iter([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]).__next__,
        )

        self.assertEqual(stats.rendered_frames, 2)
        self.assertTrue(fake.closed)


if __name__ == "__main__":
    unittest.main()
