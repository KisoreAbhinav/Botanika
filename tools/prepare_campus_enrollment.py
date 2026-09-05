#!/usr/bin/env python3
"""Materialize the reviewed campus enrollment subset from its ZIP archive.

The tracked manifest contains only relative archive member names and review
metadata.  This tool validates the archive, extracts only accepted photos into
``train/<label>/``, and leaves all excluded photos in the source archive.  The
materialized tree is intentionally ignored by Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = PROJECT_ROOT / "Campus Flora.zip"
DEFAULT_MANIFEST = PROJECT_ROOT / "data" / "campus" / "enrollment-manifest.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "campus" / "enrollment"
MANIFEST_FORMAT = "botanika-campus-enrollment-manifest-1"
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})


class PreparationError(ValueError):
    """Raised when the reviewed archive/manifest cannot be materialized safely."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError(f"could not read manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("format") != MANIFEST_FORMAT:
        raise PreparationError(f"unsupported enrollment manifest: {path}")
    return value


def _validate_member_name(name: str) -> None:
    # ZIP names are POSIX paths even when the archive was produced on
    # Windows.  Reject backslashes and empty components before
    # ``PurePosixPath`` normalises them away; otherwise a path that looks
    # harmless after parsing could materialise differently on another OS.
    if "\x00" in name or "\\" in name or "//" in name:
        raise PreparationError(f"unsafe ZIP member path: {name!r}")
    path = PurePosixPath(name)
    if (
        not name
        or path.is_absolute()
        or name.startswith("/")
        or ".." in path.parts
        or "." in path.parts
        or "" in path.parts
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in name)
    ):
        raise PreparationError(f"unsafe ZIP member path: {name!r}")


def _archive_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    members: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        _validate_member_name(info.filename)
        mode = (info.external_attr >> 16) & 0xF000
        if mode == stat.S_IFLNK:
            raise PreparationError(f"symbolic links are not allowed in the archive: {info.filename}")
        if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise PreparationError(f"special ZIP member is not allowed: {info.filename}")
        if info.is_dir():
            continue
        if info.filename in members:
            raise PreparationError(f"duplicate ZIP member: {info.filename}")
        members[info.filename] = info
    return members


def _safe_filename(value: object, *, context: str) -> str:
    filename = str(value or "").strip()
    path = PurePosixPath(filename)
    if (
        not filename
        or path.name != filename
        or path.is_absolute()
        or filename in {".", ".."}
        or "\\" in filename
        or "\x00" in filename
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in filename)
        or Path(filename).suffix.lower() not in IMAGE_SUFFIXES
    ):
        raise PreparationError(f"{context} contains an unsafe image filename: {filename!r}")
    return filename


def _safe_label(value: object) -> str:
    label = str(value or "").strip()
    if (
        not label
        or label in {".", ".."}
        or "/" in label
        or "\\" in label
        or "\x00" in label
        or label.startswith(".")
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in label)
    ):
        raise PreparationError(f"unsafe enrollment label: {label!r}")
    return label


def _reviewed_files(
    manifest: dict[str, object], members: dict[str, zipfile.ZipInfo]
) -> tuple[dict[str, list[str]], set[str], dict[str, str]]:
    prefix = str(manifest.get("archive_prefix") or "")
    prefix_path = PurePosixPath(prefix)
    if (
        not prefix
        or not prefix.endswith("/")
        or prefix != prefix.rstrip("/") + "/"
        or prefix_path.is_absolute()
        or ".." in prefix_path.parts
    ):
        raise PreparationError("manifest archive_prefix must be a safe relative directory ending in '/'")
    _validate_member_name(prefix.rstrip("/"))

    classes = manifest.get("accepted_classes")
    if not isinstance(classes, list) or not classes:
        raise PreparationError("manifest accepted_classes must be a non-empty list")
    raw_hashes = manifest.get("file_sha256")
    if not isinstance(raw_hashes, dict) or not raw_hashes:
        raise PreparationError("manifest file_sha256 must be a non-empty filename-to-SHA-256 object")
    file_hashes: dict[str, str] = {}
    for raw_filename, raw_digest in raw_hashes.items():
        filename = _safe_filename(raw_filename, context="file_sha256")
        if filename in file_hashes:
            raise PreparationError(f"duplicate file hash entry: {filename}")
        digest = str(raw_digest or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PreparationError(f"file_sha256 has an invalid SHA-256 for {filename}")
        file_hashes[filename] = digest
    labels: dict[str, list[str]] = {}
    used: set[str] = set()
    declared_hashes: dict[str, str] = {}
    for item in classes:
        if not isinstance(item, dict):
            raise PreparationError("accepted_classes entries must be objects")
        label = _safe_label(item.get("label"))
        if label in labels:
            raise PreparationError(f"duplicate accepted label: {label}")
        filenames = item.get("filenames")
        if not isinstance(filenames, list) or not filenames:
            raise PreparationError(f"accepted label {label!r} has no filenames")
        selected: list[str] = []
        for raw_filename in filenames:
            filename = _safe_filename(raw_filename, context=label)
            member = prefix + filename
            if member not in members:
                raise PreparationError(f"manifest member is absent from archive: {member}")
            if member in used:
                raise PreparationError(f"image is assigned to more than one accepted label: {filename}")
            declared_digest = file_hashes.get(filename)
            if declared_digest is None:
                raise PreparationError(f"file_sha256 is missing an entry for {filename}")
            used.add(member)
            declared_hashes[member] = declared_digest
            selected.append(filename)
        labels[label] = selected

    exclusions = manifest.get("exclusions")
    if not isinstance(exclusions, list):
        raise PreparationError("manifest exclusions must be a list")
    excluded: set[str] = set()
    for item in exclusions:
        if not isinstance(item, dict):
            raise PreparationError("exclusions entries must be objects")
        filename = _safe_filename(item.get("filename"), context="exclusion")
        member = prefix + filename
        if member not in members:
            raise PreparationError(f"excluded member is absent from archive: {member}")
        declared_digest = file_hashes.get(filename)
        if declared_digest is None:
            raise PreparationError(f"file_sha256 is missing an entry for {filename}")
        if member in used or member in excluded:
            raise PreparationError(f"image appears in multiple manifest decisions: {filename}")
        excluded.add(member)
        declared_hashes[member] = declared_digest

    all_archive_images = {
        member
        for member in members
        if PurePosixPath(member).suffix.lower() in IMAGE_SUFFIXES
    }
    archive_images = {
        member
        for member in all_archive_images
        if member.startswith(prefix)
    }
    outside_prefix = all_archive_images - archive_images
    if outside_prefix:
        raise PreparationError(
            "archive images must be below archive_prefix: " + ", ".join(sorted(outside_prefix)[:5])
        )
    decisions = used | excluded
    archive_image_names = {member[len(prefix) :] for member in archive_images}
    if set(file_hashes) != archive_image_names:
        missing = sorted(archive_image_names - set(file_hashes))
        extra = sorted(set(file_hashes) - archive_image_names)
        details = []
        if missing:
            details.append("missing file hashes: " + ", ".join(missing[:5]))
        if extra:
            details.append("file hashes not present as archive images: " + ", ".join(extra[:5]))
        raise PreparationError("manifest file_sha256 must cover every archive image (" + "; ".join(details) + ")")
    if archive_images != decisions:
        missing = sorted(archive_images - decisions)
        undeclared = sorted(decisions - archive_images)
        details = []
        if missing:
            details.append("unreviewed archive images: " + ", ".join(missing[:5]))
        if undeclared:
            details.append("manifest members not present as archive images: " + ", ".join(undeclared[:5]))
        raise PreparationError("manifest must account for every archive image (" + "; ".join(details) + ")")
    return labels, excluded, declared_hashes


def _sha256_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = hashlib.sha256()
    with archive.open(info, "r") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize(archive_path: Path, manifest_path: Path, output_path: Path, *, replace: bool = False) -> dict[str, object]:
    archive_path = archive_path.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if not archive_path.is_file():
        raise PreparationError(f"archive does not exist: {archive_path}")
    if not manifest_path.is_file():
        raise PreparationError(f"manifest does not exist: {manifest_path}")
    manifest = _load_manifest(manifest_path)
    declared_archive_filename = manifest.get("archive_filename")
    if declared_archive_filename is not None and str(declared_archive_filename) != archive_path.name:
        raise PreparationError(
            f"archive filename mismatch: manifest expects {declared_archive_filename!r}, actual {archive_path.name!r}"
        )
    expected_archive_sha256 = str(manifest.get("archive_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_archive_sha256):
        raise PreparationError("manifest archive_sha256 must be a lowercase SHA-256")
    if expected_archive_sha256 != _sha256(archive_path):
        raise PreparationError(
            f"archive checksum mismatch: manifest expects {expected_archive_sha256}, actual {_sha256(archive_path)}"
        )

    try:
        archive = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PreparationError(f"could not open archive {archive_path}: {exc}") from exc
    with archive:
        members = _archive_members(archive)
        declared_member_count = manifest.get("archive_member_count")
        actual_member_count = len(archive.infolist())
        if (
            not isinstance(declared_member_count, int)
            or isinstance(declared_member_count, bool)
            or declared_member_count != actual_member_count
        ):
            raise PreparationError(
                f"manifest archive_member_count={declared_member_count!r} does not match archive entries={actual_member_count}"
            )
        try:
            corrupt_member = archive.testzip()
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise PreparationError(f"archive CRC verification failed: {exc}") from exc
        if corrupt_member is not None:
            raise PreparationError(f"archive CRC verification failed for member: {corrupt_member}")
        labels, excluded, declared_hashes = _reviewed_files(manifest, members)
        for member, expected_hash in declared_hashes.items():
            actual_hash = _sha256_member(archive, members[member])
            if actual_hash != expected_hash:
                raise PreparationError(
                    f"file checksum mismatch for {member}: manifest expects {expected_hash}, actual {actual_hash}"
                )
        expected_count = sum(len(files) for files in labels.values())
        declared_count = manifest.get("accepted_image_count")
        if declared_count is not None and int(declared_count) != expected_count:
            raise PreparationError(
                f"manifest accepted_image_count={declared_count} does not match filenames={expected_count}"
            )
        declared_excluded = manifest.get("excluded_image_count")
        if declared_excluded is not None and int(declared_excluded) != len(excluded):
            raise PreparationError(
                f"manifest excluded_image_count={declared_excluded} does not match filenames={len(excluded)}"
            )
        declared_images = manifest.get("archive_image_count")
        if declared_images is not None and int(declared_images) != expected_count + len(excluded):
            raise PreparationError(
                f"manifest archive_image_count={declared_images} does not match reviewed images={expected_count + len(excluded)}"
            )

        if output_path.exists() and not replace:
            raise PreparationError(f"output already exists; pass --replace to refresh only this generated tree: {output_path}")
        if output_path.is_symlink() or (output_path.exists() and not output_path.is_dir()):
            raise PreparationError(f"output path must be a directory or absent: {output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        staging = output_path.parent / f".{output_path.name}.staging-{os.getpid()}"
        if staging.exists():
            raise PreparationError(f"staging path already exists: {staging}")
        staging.mkdir()
        try:
            train = staging / "train"
            for label in sorted(labels, key=str.casefold):
                filenames = labels[label]
                destination = train / label
                destination.mkdir(parents=True)
                for filename in sorted(filenames, key=str.casefold):
                    with archive.open(members[str(manifest["archive_prefix"]) + filename], "r") as source:
                        with (destination / filename).open("wb") as target:
                            shutil.copyfileobj(source, target)
            if output_path.exists():
                shutil.rmtree(output_path)
            staging.replace(output_path)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    return {
        "archive_sha256": expected_archive_sha256,
        "output": str(output_path),
        "labels": {label: len(labels[label]) for label in sorted(labels, key=str.casefold)},
        "accepted_image_count": sum(len(files) for files in labels.values()),
        "excluded_image_count": len(excluded),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace the exact generated output directory if it already exists",
    )
    args = parser.parse_args(argv)
    try:
        result = materialize(args.archive, args.manifest, args.output, replace=args.replace)
    except (OSError, PreparationError, ValueError, zipfile.BadZipFile) as exc:
        print(f"campus enrollment preparation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
