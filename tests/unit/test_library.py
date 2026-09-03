from __future__ import annotations

import tempfile
import time
from pathlib import Path
import unittest

import numpy as np

from botanika.storage import DemoLibrary
from botanika.vision.classification import ClassificationPipeline, DummyClassifier
from botanika.vision.detection import BoundingBox
from botanika.vision.quality import CropStore


class DemoLibraryTests(unittest.TestCase):
    def test_saved_at_is_a_wall_clock_timestamp_and_survives_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = CropStore(root / "temp").save(
                np.full((120, 120, 3), 100, dtype=np.uint8),
                BoundingBox(10, 10, 110, 110),
            )
            run = ClassificationPipeline(DummyClassifier()).classify_capture(capture)
            before = time.time()
            library = DemoLibrary(root / "library.sqlite", root / "media")
            record = library.save(capture, run)
            library.close()

            self.assertGreaterEqual(record.saved_at, before)
            self.assertLessEqual(record.saved_at, time.time())
            reopened = DemoLibrary(root / "library.sqlite", root / "media")
            self.addCleanup(reopened.close)
            self.assertEqual(reopened.get(record.id).saved_at, record.saved_at)


if __name__ == "__main__":
    unittest.main()
