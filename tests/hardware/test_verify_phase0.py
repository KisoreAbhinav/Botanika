from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT_ROOT / "tools" / "verify_phase0.py"
SPEC = importlib.util.spec_from_file_location("verify_phase0", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verify_phase0 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_phase0)


class ProbeCameraTests(unittest.TestCase):
    def run_probe_with_capture(self, capture_bytes: bytes, returncode: int = 0):
        def fake_run_command(args: list[str], timeout: float = 10.0):
            if "--list-cameras" in args:
                return {"returncode": 0, "stdout": "Available cameras\n0: imx708", "stderr": ""}

            output_path = Path(args[args.index("--output") + 1])
            if capture_bytes:
                output_path.write_bytes(capture_bytes)
            return {"returncode": returncode, "stdout": "", "stderr": ""}

        with (
            mock.patch.object(verify_phase0.shutil, "which", return_value="/usr/bin/tool"),
            mock.patch.object(verify_phase0, "run_command", side_effect=fake_run_command),
            mock.patch.object(verify_phase0.tempfile, "NamedTemporaryFile") as named_temp,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            capture_path = Path(temp_dir) / "capture.jpg"
            named_temp.return_value.__enter__.return_value.name = str(capture_path)
            return verify_phase0.probe_camera(probe_capture=True)

    def test_valid_jpeg_passes_capture_gate(self):
        result = self.run_probe_with_capture(b"\xff\xd8pixels\xff\xd9")

        self.assertEqual("PASS", result["status"])
        self.assertEqual("PASS", result["capture"]["status"])
        self.assertFalse(Path(result["capture"]["path"]).exists())

    def test_invalid_jpeg_blocks_camera_gate(self):
        result = self.run_probe_with_capture(b"not-a-jpeg")

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("BLOCKED", result["capture"]["status"])

    def test_missing_capture_blocks_camera_gate(self):
        result = self.run_probe_with_capture(b"", returncode=1)

        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("BLOCKED", result["capture"]["status"])


if __name__ == "__main__":
    unittest.main()
