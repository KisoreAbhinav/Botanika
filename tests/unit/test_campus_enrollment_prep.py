from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.prepare_campus_enrollment import PreparationError, materialize


class CampusEnrollmentPreparationTests(unittest.TestCase):
    def test_materializes_only_accepted_images_and_verifies_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "Campus Flora.zip"
            members = {
                "Campus Flora/accepted.jpg": b"accepted image bytes",
                "Campus Flora/excluded.jpg": b"excluded image bytes",
            }
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("Campus Flora/", b"")
                for name, content in members.items():
                    bundle.writestr(name, content)
            hashes = {
                name.rsplit("/", 1)[1]: hashlib.sha256(content).hexdigest()
                for name, content in members.items()
            }
            manifest = _manifest(archive, hashes)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            result = materialize(archive, manifest_path, root / "out")

            self.assertEqual(result["accepted_image_count"], 1)
            self.assertEqual(result["excluded_image_count"], 1)
            self.assertEqual(
                (root / "out" / "train" / "Accepted" / "accepted.jpg").read_bytes(),
                members["Campus Flora/accepted.jpg"],
            )
            self.assertFalse((root / "out" / "train" / "Accepted" / "excluded.jpg").exists())

    def test_rejects_manifest_file_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "Campus Flora.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("Campus Flora/accepted.jpg", b"real bytes")
            manifest = _manifest(archive, {"accepted.jpg": "0" * 64})
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(PreparationError, "file checksum mismatch"):
                materialize(archive, manifest_path, root / "out")

    def test_rejects_unsafe_zip_member_before_materialization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "Campus Flora.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("Campus Flora/accepted.jpg", b"good")
                bundle.writestr("Campus Flora/../escape.jpg", b"bad")
            digest = hashlib.sha256(b"good").hexdigest()
            manifest = _manifest(archive, {"accepted.jpg": digest, "escape.jpg": "0" * 64})
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(PreparationError, "unsafe ZIP member path"):
                materialize(archive, manifest_path, root / "out")

    def test_rejects_unaccounted_archive_image(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "Campus Flora.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("Campus Flora/accepted.jpg", b"accepted")
                bundle.writestr("Campus Flora/unreviewed.jpg", b"unreviewed")
            manifest = _manifest(
                archive,
                {"accepted.jpg": hashlib.sha256(b"accepted").hexdigest()},
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(PreparationError, "file_sha256 must cover every archive image"):
                materialize(archive, manifest_path, root / "out")

    def test_rejects_archive_image_outside_reviewed_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "Campus Flora.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("Campus Flora/accepted.jpg", b"accepted")
                bundle.writestr("outside.jpg", b"outside")
            manifest = _manifest(
                archive,
                {"accepted.jpg": hashlib.sha256(b"accepted").hexdigest()},
            )
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(PreparationError, "below archive_prefix"):
                materialize(archive, manifest_path, root / "out")


def _manifest(archive: Path, hashes: dict[str, str]) -> dict[str, object]:
    with zipfile.ZipFile(archive) as bundle:
        member_count = len(bundle.infolist())
    return {
        "format": "botanika-campus-enrollment-manifest-1",
        "archive_filename": archive.name,
        "archive_prefix": "Campus Flora/",
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "archive_member_count": member_count,
        "archive_image_count": len(hashes),
        "accepted_image_count": 1,
        "excluded_image_count": len(hashes) - 1,
        "file_sha256": hashes,
        "accepted_classes": [{"label": "Accepted", "filenames": ["accepted.jpg"]}],
        "exclusions": [
            {"filename": filename, "reason": "test"}
            for filename in hashes
            if filename != "accepted.jpg"
        ],
    }


if __name__ == "__main__":
    unittest.main()
