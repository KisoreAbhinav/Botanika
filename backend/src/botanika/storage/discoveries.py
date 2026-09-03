"""Authoritative crop-only discovery library for the Phase 6 runtime."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time
import uuid
from typing import Any, Callable, Iterable
import zipfile

import cv2

from botanika.vision.classification import ClassificationRun
from botanika.vision.quality import CaptureResult

from .database import SQLiteDatabase


class DiscoveryError(RuntimeError):
    """Raised when a discovery cannot be safely persisted or restored."""


@dataclass(frozen=True, slots=True)
class LibraryRecord:
    """One accepted observation and its linked crop image."""

    id: str
    species_id: str
    saved_at: float
    observed_at: float
    crop_path: Path
    crop_relative_path: str
    crop_hash: str
    width: int
    height: int
    confidence: float
    classifier_version: str
    request_id: str
    common_name: str
    scientific_name: str
    family: str
    category: str
    native_status: str
    is_native: bool
    conservation_status: str
    ecology: str
    short_notes: str
    sources: tuple[str, ...]
    note: str | None = None
    thumbnail_path: str | None = None
    is_stub: bool = False
    demo_label: str = ""

    @property
    def observation_id(self) -> str:
        return self.id

    @property
    def crop_filename(self) -> str:
        # Kept for the Phase 5 flat-record contract; it is relative, never a
        # basename-only guess that could collide across species directories.
        return self.crop_relative_path

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "observation_id": self.id,
            "species_id": self.species_id,
            "saved_at": self.saved_at,
            "observed_at": self.observed_at,
            "crop_path": str(self.crop_path),
            "crop_relative_path": self.crop_relative_path,
            "crop_filename": self.crop_filename,
            "crop_hash": self.crop_hash,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
            "classifier_version": self.classifier_version,
            "request_id": self.request_id,
            "common_name": self.common_name,
            "scientific_name": self.scientific_name,
            "family": self.family,
            "category": self.category,
            "native_status": self.native_status,
            "is_native": self.is_native,
            "conservation_status": self.conservation_status,
            "ecology": self.ecology,
            "short_notes": self.short_notes,
            "sources": list(self.sources),
            "note": self.note,
            "thumbnail_path": self.thumbnail_path,
            "is_stub": self.is_stub,
            "demo_label": self.demo_label,
        }


class DiscoveryLibrary:
    """SQLite-plus-filesystem service that owns every real discovery write."""

    def __init__(
        self,
        database_path: Path,
        media_dir: Path,
        *,
        deduplication_seconds: float = 5.0,
        quota_bytes: int = 2 * 1024 * 1024 * 1024,
        quota_observations: int = 10000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if deduplication_seconds < 0:
            raise ValueError("deduplication_seconds must not be negative")
        if quota_bytes <= 0 or quota_observations <= 0:
            raise ValueError("library quotas must be positive")
        self.database = SQLiteDatabase(Path(database_path))
        self.media_dir = Path(media_dir).resolve()
        self.deduplication_seconds = float(deduplication_seconds)
        self.quota_bytes = int(quota_bytes)
        self.quota_observations = int(quota_observations)
        self._clock = clock
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.recover_orphans()

    @property
    def database_path(self) -> Path:
        return self.database.path

    def probe(self) -> str:
        result = self.database.probe()
        if result != "ok":
            return result
        try:
            self.media_dir.mkdir(parents=True, exist_ok=True)
            probe = self.media_dir / ".write-probe"
            probe.write_bytes(b"ok")
            probe.unlink(missing_ok=True)
            return "ok"
        except OSError as exc:
            return f"storage error: {exc}"

    def save(
        self,
        capture: CaptureResult,
        run: ClassificationRun,
        *,
        request_name: str = "scan",
        note: str | None = None,
        observed_at: float | None = None,
        position: dict[str, Any] | None = None,
    ) -> LibraryRecord:
        """Copy, verify, and commit one accepted crop with its observation."""

        if not isinstance(capture, CaptureResult):
            raise TypeError("capture must be a CaptureResult")
        if not isinstance(run, ClassificationRun):
            raise TypeError("run must be a ClassificationRun")
        result = run.result
        if not result.is_accepted:
            raise ValueError("only accepted results may be saved")
        if result.is_stub:
            raise ValueError("stub results are not part of the real discovery library")
        if capture.path is None or not capture.path.is_file():
            raise ValueError("cannot save a capture without a crop file")
        if not result.species_id:
            raise ValueError("accepted result has no stable species ID")
        if note is not None:
            note = str(note).strip() or None
            if note is not None and len(note) > 2000:
                raise ValueError("observation note must be at most 2000 characters")
        observed = self._clock() if observed_at is None else float(observed_at)
        if not math.isfinite(observed) or observed < 0:
            raise ValueError("observed_at must be a finite non-negative timestamp")

        image = cv2.imread(str(capture.path), cv2.IMREAD_COLOR)
        if image is None or image.ndim != 3 or image.shape[0] <= 0 or image.shape[1] <= 0:
            raise ValueError("crop could not be decoded before save")
        crop_size = capture.path.stat().st_size
        crop_hash = _sha256(capture.path)
        duplicate = self._find_recent_duplicate(crop_hash)
        if duplicate is not None:
            return duplicate
        thumbnail_bytes = _thumbnail_bytes(image)
        self._check_quota(crop_size + len(thumbnail_bytes))

        species = self._species_row(result.species_id)
        if species is None:
            raise ValueError(f"species ID is not in the seeded catalog: {result.species_id}")
        now = self._clock()
        observation_id = uuid.uuid4().hex
        safe_species = _safe_path_component(result.species_id)
        relative_path = Path(safe_species) / f"observation-{int(now * 1000)}-{crop_hash[:12]}-{observation_id[:8]}.png"
        thumbnail_relative_path = relative_path.with_suffix(".thumb.jpg")
        destination = (self.media_dir / relative_path).resolve()
        thumbnail_destination = (self.media_dir / thumbnail_relative_path).resolve()
        if not destination.is_relative_to(self.media_dir):
            raise DiscoveryError("computed crop path escaped the managed media directory")
        staging_dir = self.media_dir / ".staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging = staging_dir / f"{observation_id}.tmp"
        try:
            shutil.copyfile(capture.path, staging)
            if not staging.is_file() or staging.stat().st_size <= 0 or _sha256(staging) != crop_hash:
                raise DiscoveryError("crop copy failed verification")
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
            thumbnail_destination.write_bytes(thumbnail_bytes)
            if thumbnail_destination.stat().st_size <= 0:
                raise DiscoveryError("thumbnail copy failed verification")
            record = LibraryRecord(
                id=observation_id,
                species_id=str(species["species_id"]),
                saved_at=now,
                observed_at=observed,
                crop_path=destination,
                crop_relative_path=relative_path.as_posix(),
                crop_hash=crop_hash,
                width=int(image.shape[1]),
                height=int(image.shape[0]),
                confidence=float(result.confidence or 0.0),
                classifier_version=result.classifier_version,
                request_id=run.request_id or request_name,
                common_name=str(species["common_name"]),
                scientific_name=str(species["scientific_name"]),
                family=str(species["family"]),
                category=str(species["category"]),
                native_status=str(species["native_status"]),
                is_native=bool(int(species["is_native"])),
                conservation_status=str(species["conservation_status"]),
                ecology=str(species["ecology"]),
                short_notes=str(species["short_notes"]),
                sources=tuple(result.sources),
                note=note,
                thumbnail_path=thumbnail_relative_path.as_posix(),
            )
            with self.database.transaction() as connection:
                connection.execute(
                    """
                    INSERT INTO discoveries(
                        observation_id, species_id, observed_at, saved_at, confidence,
                        classifier_version, request_id, result_snapshot, note
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.id, record.species_id, record.observed_at, record.saved_at,
                        record.confidence, record.classifier_version, record.request_id,
                        json.dumps(result.to_dict(), sort_keys=True), record.note,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO discovery_images(
                        image_id, observation_id, crop_path, thumbnail_path, crop_hash,
                        width, height, mime_type, byte_size, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex, record.id, record.crop_relative_path, record.thumbnail_path,
                        record.crop_hash, record.width, record.height, "image/png",
                        destination.stat().st_size + thumbnail_destination.stat().st_size,
                        record.saved_at,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO library_species(species_id, first_seen, last_seen, observation_count)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(species_id) DO UPDATE SET
                        first_seen = MIN(first_seen, excluded.first_seen),
                        last_seen = MAX(last_seen, excluded.last_seen),
                        observation_count = observation_count + 1
                    """,
                    (record.species_id, record.observed_at, record.observed_at),
                )
                if position is not None:
                    _insert_position(connection, record.id, position, record.observed_at)
        except Exception:
            destination.unlink(missing_ok=True)
            thumbnail_destination.unlink(missing_ok=True)
            staging.unlink(missing_ok=True)
            raise
        finally:
            try:
                staging_dir.rmdir()
            except OSError:
                pass
        return record

    def list_records(
        self,
        *,
        category: str | None = None,
        species_id: str | None = None,
        limit: int | None = None,
    ) -> list[LibraryRecord]:
        clauses = ["d.deleted_at IS NULL"]
        params: list[Any] = []
        if category and category.lower() != "all":
            clauses.append("lower(s.category) = lower(?)")
            params.append(category)
        if species_id:
            clauses.append("s.species_id = ?")
            params.append(species_id)
        query = """
            SELECT d.observation_id, d.species_id, d.observed_at, d.saved_at,
                   d.confidence, d.classifier_version, d.request_id, d.result_snapshot,
                   d.note, i.crop_path, i.thumbnail_path, i.crop_hash, i.width,
                   i.height, i.mime_type, i.byte_size,
                   s.scientific_name, s.common_name, s.family, s.category,
                   s.native_status, s.is_native, s.conservation_status, s.ecology,
                   s.short_notes
            FROM discoveries d
            JOIN discovery_images i ON i.observation_id = d.observation_id
            JOIN species s ON s.species_id = d.species_id
            WHERE %s
            ORDER BY d.observed_at DESC, d.saved_at DESC
        """ % " AND ".join(clauses)
        if limit is not None:
            if limit <= 0:
                return []
            query += " LIMIT ?"
            params.append(int(limit))
        with self.database.transaction(immediate=False) as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._record_from_row(row) for row in rows]

    def list_grouped(self, *, category: str | None = None) -> list[dict[str, Any]]:
        groups: dict[str, list[LibraryRecord]] = {}
        for record in self.list_records(category=category):
            groups.setdefault(record.species_id, []).append(record)
        values: list[dict[str, Any]] = []
        for records in groups.values():
            records.sort(key=lambda item: item.observed_at, reverse=True)
            newest = records[0]
            values.append(
                {
                    "species_id": newest.species_id,
                    "common_name": newest.common_name,
                    "scientific_name": newest.scientific_name,
                    "family": newest.family,
                    "category": newest.category,
                    "native_status": newest.native_status,
                    "is_native": newest.is_native,
                    "conservation_status": newest.conservation_status,
                    "ecology": newest.ecology,
                    "short_notes": newest.short_notes,
                    "observation_count": len(records),
                    "newest": newest.to_dict(),
                    "observations": [item.to_dict() for item in records],
                }
            )
        return sorted(values, key=lambda item: str(item["common_name"]).lower())

    def categories(self) -> list[str]:
        with self.database.transaction(immediate=False) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT s.category FROM species s
                JOIN discoveries d ON d.species_id = s.species_id
                WHERE d.deleted_at IS NULL ORDER BY s.category
                """
            ).fetchall()
        return [str(row[0]) for row in rows]

    def get(self, record_id: str) -> LibraryRecord | None:
        records = self.list_records()
        return next((record for record in records if record.id == record_id), None)

    def delete(self, record_id: str, *, confirmed: bool = False) -> bool:
        if not confirmed:
            raise ValueError("deleting a library record requires explicit confirmation")
        record = self.get(record_id)
        if record is None:
            return False
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM discoveries WHERE observation_id = ?", (record_id,))
            connection.execute(
                """
                DELETE FROM library_species
                WHERE species_id = ? AND NOT EXISTS(
                    SELECT 1 FROM discoveries WHERE species_id = ? AND deleted_at IS NULL
                )
                """,
                (record.species_id, record.species_id),
            )
            connection.execute(
                """
                UPDATE library_species SET
                    observation_count = (
                        SELECT COUNT(*) FROM discoveries
                        WHERE species_id = library_species.species_id AND deleted_at IS NULL
                    ),
                    last_seen = COALESCE((
                        SELECT MAX(observed_at) FROM discoveries
                        WHERE species_id = library_species.species_id AND deleted_at IS NULL
                    ), last_seen)
                WHERE species_id = ?
                """,
                (record.species_id,),
            )
        for relative_path in (record.crop_relative_path, record.thumbnail_path):
            if relative_path:
                try:
                    self._unlink_managed(relative_path)
                except OSError:
                    # A confirmed DB delete must not be undone by a missing or
                    # read-only media file; recovery will report the orphan.
                    pass
        return True

    def update_note(self, record_id: str, note: str | None) -> LibraryRecord | None:
        note = str(note).strip() if note is not None else None
        if note == "":
            note = None
        if note is not None and len(note) > 2000:
            raise ValueError("observation note must be at most 2000 characters")
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE discoveries SET note = ? WHERE observation_id = ? AND deleted_at IS NULL",
                (note, record_id),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(record_id)

    def usage(self) -> dict[str, int]:
        with self.database.transaction(immediate=False) as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS observations, COALESCE(SUM(i.byte_size), 0) AS bytes
                FROM discoveries d JOIN discovery_images i ON i.observation_id = d.observation_id
                WHERE d.deleted_at IS NULL
                """
            ).fetchone()
        return {"observations": int(row["observations"]), "bytes": int(row["bytes"])}

    def export_archive(self, destination: Path | None = None) -> Path:
        """Export a consistent DB snapshot and every referenced crop together."""

        if destination is None:
            destination = self.media_dir.parent.parent / "backups" / f"botanika-export-{int(self._clock())}.zip"
        destination = Path(destination).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        records = self.list_records()
        with tempfile.TemporaryDirectory(prefix="botanika-export-", dir=str(destination.parent)) as temp:
            temp_db = Path(temp) / "database.sqlite"
            self.database.backup_to(temp_db)
            manifest = {
                "format": "botanika-discovery-1",
                "created_at": self._clock(),
                "database": "database.sqlite",
                "media_root": "media",
                "catalog": "database.sqlite",
                "images": [
                    {
                        "observation_id": record.id,
                        "path": record.crop_relative_path,
                        "sha256": record.crop_hash,
                        "thumbnail_path": record.thumbnail_path,
                        "thumbnail_sha256": _sha256(self.media_dir / record.thumbnail_path)
                        if record.thumbnail_path and (self.media_dir / record.thumbnail_path).is_file()
                        else None,
                    }
                    for record in records
                ],
            }
            temporary_archive = Path(temp) / "archive.zip"
            with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(temp_db, "database.sqlite")
                archive.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
                for record in records:
                    if record.crop_path.is_file():
                        archive.write(record.crop_path, f"media/{record.crop_relative_path}")
                    if record.thumbnail_path:
                        thumbnail = self.media_dir / _validated_relative(record.thumbnail_path)
                        if thumbnail.is_file():
                            archive.write(thumbnail, f"media/{record.thumbnail_path}")
            os.replace(temporary_archive, destination)
        return destination

    backup = export_archive

    def restore_archive(self, archive_path: Path, *, confirmed: bool = False) -> Path:
        """Restore a previously exported archive after explicit confirmation."""

        if not confirmed:
            raise ValueError("restoring the library requires explicit confirmation")
        archive_path = Path(archive_path)
        if not archive_path.is_file():
            raise FileNotFoundError(archive_path)
        with tempfile.TemporaryDirectory(prefix="botanika-restore-") as temp:
            extract_root = Path(temp) / "contents"
            extract_root.mkdir()
            with zipfile.ZipFile(archive_path) as archive:
                _validate_archive_members(archive.namelist())
                archive.extractall(extract_root)
            manifest_path = extract_root / "manifest.json"
            database_path = extract_root / "database.sqlite"
            if not manifest_path.is_file() or not database_path.is_file():
                raise DiscoveryError("backup is missing its manifest or database")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("format") != "botanika-discovery-1":
                raise DiscoveryError("unsupported Botanika backup format")
            images = manifest.get("images")
            if not isinstance(images, list):
                raise DiscoveryError("backup image manifest is malformed")
            for item in images:
                if not isinstance(item, dict) or not item.get("observation_id"):
                    raise DiscoveryError("backup image manifest contains an invalid observation")
                relative = _validated_relative(str(item.get("path") or ""))
                source = extract_root / "media" / relative
                if not source.is_file() or _sha256(source) != str(item.get("sha256")):
                    raise DiscoveryError(f"backup crop failed verification: {relative}")
                thumbnail_value = item.get("thumbnail_path")
                if thumbnail_value:
                    thumbnail_relative = _validated_relative(str(thumbnail_value))
                    thumbnail = extract_root / "media" / thumbnail_relative
                    if not thumbnail.is_file() or _sha256(thumbnail) != str(item.get("thumbnail_sha256")):
                        raise DiscoveryError(f"backup thumbnail failed verification: {thumbnail_relative}")
            check = sqlite3.connect(str(database_path))
            try:
                integrity = check.execute("PRAGMA integrity_check").fetchone()
                if integrity is None or str(integrity[0]).lower() != "ok":
                    raise DiscoveryError("backup database failed SQLite integrity verification")
                if check.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise DiscoveryError("backup database contains broken foreign-key linkage")
                required = {"species", "discoveries", "discovery_images", "library_species"}
                present = {
                    str(row[0]) for row in check.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if not required.issubset(present):
                    raise DiscoveryError("backup database does not contain the Phase 6 library schema")
                database_images = check.execute(
                    "SELECT observation_id, crop_path, thumbnail_path, crop_hash FROM discovery_images"
                ).fetchall()
                count = len(database_images)
                if count != len(images):
                    raise DiscoveryError("backup database and image manifest disagree")
                database_by_id = {
                    str(row[0]): (str(row[1]), row[2], str(row[3]))
                    for row in database_images
                }
                manifest_ids = [str(item["observation_id"]) for item in images]
                if len(set(manifest_ids)) != len(manifest_ids) or set(manifest_ids) != set(database_by_id):
                    raise DiscoveryError("backup observation IDs are not a one-to-one image linkage")
                for item in images:
                    observation_id = str(item["observation_id"])
                    expected = database_by_id.get(observation_id)
                    if expected is None:
                        raise DiscoveryError(
                            f"backup image manifest references an unknown observation: {observation_id}"
                        )
                    if (
                        expected[0] != _validated_relative(str(item["path"])).as_posix()
                        or (str(expected[1]) if expected[1] else None) != item.get("thumbnail_path")
                        or expected[2] != str(item.get("sha256"))
                    ):
                        raise DiscoveryError(
                            f"backup database and image manifest disagree for {observation_id}"
                        )
                incoming_catalog = {
                    str(row[0]): str(row[1])
                    for row in check.execute(
                        "SELECT key, value FROM catalog_metadata WHERE key IN "
                        "('catalog_id', 'catalog_version', 'catalog_digest')"
                    ).fetchall()
                }
                with self.database.transaction(immediate=False) as current:
                    current_catalog = {
                        str(row[0]): str(row[1])
                        for row in current.execute(
                            "SELECT key, value FROM catalog_metadata WHERE key IN "
                            "('catalog_id', 'catalog_version', 'catalog_digest')"
                        ).fetchall()
                    }
                    incoming_species = {
                        str(row[0])
                        for row in check.execute(
                            "SELECT species_id FROM species"
                        ).fetchall()
                    }
                    current_species = {
                        str(row[0])
                        for row in current.execute("SELECT species_id FROM species").fetchall()
                    }
                    if incoming_species != current_species:
                        raise DiscoveryError("backup species catalog membership is incompatible")
                    immutable_columns = (
                        "scientific_name", "common_name", "family", "region",
                        "category", "native_status", "is_native",
                        "conservation_status", "ecology", "short_notes",
                    )
                    for species_id in current_species:
                        incoming = check.execute(
                            "SELECT " + ", ".join(immutable_columns) + " FROM species WHERE species_id = ?",
                            (species_id,),
                        ).fetchone()
                        existing = current.execute(
                            "SELECT " + ", ".join(immutable_columns) + " FROM species WHERE species_id = ?",
                            (species_id,),
                        ).fetchone()
                        if incoming is None or existing is None or tuple(incoming) != tuple(existing):
                            raise DiscoveryError(
                                f"backup species metadata is incompatible: {species_id}"
                            )
                if (
                    not incoming_catalog.get("catalog_id")
                    or incoming_catalog.get("catalog_id") != current_catalog.get("catalog_id")
                ):
                    raise DiscoveryError("backup belongs to a different species catalog")
                if (
                    incoming_catalog.get("catalog_version") == current_catalog.get("catalog_version")
                    and incoming_catalog.get("catalog_digest") != current_catalog.get("catalog_digest")
                ):
                    raise DiscoveryError("backup catalog digest is inconsistent with its version")
            finally:
                check.close()

            # Stage and verify every media file before changing live state. The
            # database and media directory then move together with an explicit
            # rollback snapshot if either half of the restore fails.
            restore_id = uuid.uuid4().hex
            staged_media = self.media_dir.parent / f".{self.media_dir.name}.restore-{restore_id}"
            rollback_media = self.media_dir.parent / f".{self.media_dir.name}.rollback-{restore_id}"
            failed_media = self.media_dir.parent / f".{self.media_dir.name}.failed-{restore_id}"
            rollback_database = Path(temp) / "rollback.sqlite"
            swapped = False
            try:
                staged_media.mkdir(parents=True)
                for item in images:
                    relative = _validated_relative(str(item["path"]))
                    destination = staged_media / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(extract_root / "media" / relative, destination)
                    if _sha256(destination) != str(item["sha256"]):
                        raise DiscoveryError(f"staged crop failed verification: {relative}")
                    thumbnail_value = item.get("thumbnail_path")
                    if thumbnail_value:
                        thumbnail_relative = _validated_relative(str(thumbnail_value))
                        thumbnail_destination = staged_media / thumbnail_relative
                        thumbnail_destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(
                            extract_root / "media" / thumbnail_relative,
                            thumbnail_destination,
                        )
                        if _sha256(thumbnail_destination) != str(item["thumbnail_sha256"]):
                            raise DiscoveryError(
                                f"staged thumbnail failed verification: {thumbnail_relative}"
                            )

                self.database.backup_to(rollback_database)
                os.replace(self.media_dir, rollback_media)
                swapped = True
                os.replace(staged_media, self.media_dir)
                self.database.restore_from(database_path)
                if self.database.probe() != "ok":
                    raise DiscoveryError("restored database failed its storage probe")
                self.recover_orphans()
            except Exception as restore_error:
                rollback_errors: list[str] = []
                if swapped:
                    try:
                        self.database.restore_from(rollback_database)
                    except Exception as exc:
                        rollback_errors.append(f"database rollback failed: {exc}")
                    try:
                        if self.media_dir.exists():
                            os.replace(self.media_dir, failed_media)
                        os.replace(rollback_media, self.media_dir)
                        if failed_media.exists():
                            shutil.rmtree(failed_media)
                    except Exception as exc:
                        rollback_errors.append(f"media rollback failed: {exc}")
                if rollback_errors:
                    raise DiscoveryError(
                        "restore failed and could not be fully rolled back: "
                        + "; ".join(rollback_errors)
                    ) from restore_error
                raise
            else:
                if rollback_media.exists():
                    shutil.rmtree(rollback_media, ignore_errors=True)
            finally:
                if staged_media.exists():
                    shutil.rmtree(staged_media, ignore_errors=True)
                if failed_media.exists():
                    shutil.rmtree(failed_media, ignore_errors=True)
        return archive_path.resolve()

    restore = restore_archive

    def recover_orphans(self) -> int:
        """Remove interrupted-save staging files and unreferenced managed crops."""

        self.media_dir.mkdir(parents=True, exist_ok=True)
        referenced: set[str] = set()
        with self.database.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT crop_path, thumbnail_path FROM discovery_images"
            ).fetchall()
        for row in rows:
            for value in (row[0], row[1]):
                if not value:
                    continue
                try:
                    relative = _validated_relative(str(value))
                except DiscoveryError:
                    continue
                referenced.add(relative.as_posix())
        removed = 0
        staging = self.media_dir / ".staging"
        if staging.is_dir():
            for item in staging.iterdir():
                if item.is_file():
                    item.unlink(missing_ok=True)
                    removed += 1
            try:
                staging.rmdir()
            except OSError:
                pass
        for item in self.media_dir.rglob("*"):
            if not item.is_file() or item.name == ".write-probe":
                continue
            relative = item.relative_to(self.media_dir).as_posix()
            if relative not in referenced:
                item.unlink(missing_ok=True)
                removed += 1
        return removed

    def close(self) -> None:
        self.database.close()

    def _species_row(self, species_id: str) -> sqlite3.Row | None:
        with self.database.transaction(immediate=False) as connection:
            return connection.execute("SELECT * FROM species WHERE species_id = ?", (species_id,)).fetchone()

    def _find_recent_duplicate(self, crop_hash: str) -> LibraryRecord | None:
        now = self._clock()
        with self.database.transaction(immediate=False) as connection:
            row = connection.execute(
                """
                SELECT d.observation_id, d.species_id, d.observed_at, d.saved_at,
                       d.confidence, d.classifier_version, d.request_id, d.result_snapshot,
                       d.note, i.crop_path, i.thumbnail_path, i.crop_hash, i.width,
                       i.height, i.mime_type, i.byte_size,
                       s.scientific_name, s.common_name, s.family, s.category,
                       s.native_status, s.is_native, s.conservation_status, s.ecology,
                       s.short_notes
                FROM discoveries d JOIN discovery_images i ON i.observation_id = d.observation_id
                JOIN species s ON s.species_id = d.species_id
                WHERE d.deleted_at IS NULL AND i.crop_hash = ?
                  AND d.saved_at >= ? ORDER BY d.saved_at DESC LIMIT 1
                """,
                (crop_hash, now - self.deduplication_seconds),
            ).fetchone()
        return self._record_from_row(row) if row is not None else None

    def _check_quota(self, incoming_bytes: int) -> None:
        usage = self.usage()
        if usage["observations"] >= self.quota_observations:
            raise DiscoveryError("library observation quota has been reached")
        if usage["bytes"] + int(incoming_bytes) > self.quota_bytes:
            raise DiscoveryError("library storage quota has been reached")

    def _record_from_row(self, row: sqlite3.Row) -> LibraryRecord:
        snapshot = json.loads(str(row["result_snapshot"]))
        result_sources = snapshot.get("sources") or []
        return LibraryRecord(
            id=str(row["observation_id"]),
            species_id=str(row["species_id"]),
            saved_at=float(row["saved_at"]),
            observed_at=float(row["observed_at"]),
            crop_path=(self.media_dir / _validated_relative(str(row["crop_path"]))).resolve(),
            crop_relative_path=_validated_relative(str(row["crop_path"])).as_posix(),
            crop_hash=str(row["crop_hash"]),
            width=int(row["width"]),
            height=int(row["height"]),
            confidence=float(row["confidence"]),
            classifier_version=str(row["classifier_version"]),
            request_id=str(row["request_id"]),
            common_name=str(row["common_name"]),
            scientific_name=str(row["scientific_name"]),
            family=str(row["family"]),
            category=str(row["category"]),
            native_status=str(row["native_status"]),
            is_native=bool(int(row["is_native"])),
            conservation_status=str(row["conservation_status"]),
            ecology=str(row["ecology"]),
            short_notes=str(row["short_notes"]),
            sources=tuple(str(item) for item in result_sources),
            note=(str(row["note"]) if row["note"] is not None else None),
            thumbnail_path=(str(row["thumbnail_path"]) if row["thumbnail_path"] else None),
        )

    def _unlink_managed(self, relative_path: str) -> None:
        path = (self.media_dir / _validated_relative(relative_path)).resolve()
        if path.is_relative_to(self.media_dir):
            path.unlink(missing_ok=True)


def _insert_position(connection: sqlite3.Connection, observation_id: str, position: dict[str, Any], observed_at: float) -> None:
    try:
        latitude = float(position["latitude"])
        longitude = float(position["longitude"])
        accuracy = float(position["accuracy_m"])
        source = str(position["source"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("position requires latitude, longitude, accuracy_m, and source") from exc
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise ValueError("position latitude is out of range")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise ValueError("position longitude is out of range")
    if not math.isfinite(accuracy) or accuracy < 0 or not source:
        raise ValueError("position accuracy/source is invalid")
    connection.execute(
        """
        INSERT INTO positioning_samples(
            sample_id, observation_id, latitude, longitude, accuracy_m, source, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (uuid.uuid4().hex, observation_id, latitude, longitude, accuracy, source, observed_at),
    )


def _safe_path_component(value: str) -> str:
    result = "".join(character if character.isalnum() or character in "-_" else "_" for character in value)
    return result.strip("._") or "species"


def _validated_relative(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or path == Path("."):
        raise DiscoveryError(f"unsafe managed media path: {value!r}")
    return path


def _validate_archive_members(names: Iterable[str]) -> None:
    for name in names:
        if name.startswith("/") or ".." in Path(name).parts:
            raise DiscoveryError(f"unsafe backup member: {name!r}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _thumbnail_bytes(image) -> bytes:
    height, width = image.shape[:2]
    scale = min(1.0, 96.0 / max(height, width))
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    thumbnail = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
    ok, encoded = cv2.imencode(".jpg", thumbnail, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    if not ok:
        raise DiscoveryError("thumbnail encoding failed")
    return encoded.tobytes()
