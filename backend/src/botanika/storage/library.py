"""Demo-only library persistence clearly separated from real discoveries.

Phase 5 saves exactly one accepted stub crop per record.  Every row is marked
``is_stub`` and labelled ``DEMO DATA`` so the Phase 6 real-species library can
share this module's boundaries without ever mixing demo records into real
discoveries.  The full frame is never persisted: only the crop file is copied
from the transient Phase 3 store.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import uuid
from typing import Callable

from botanika.vision.classification import DEMO_DATA_LABEL, ClassificationRun
from botanika.vision.quality import CaptureResult

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class DemoLibraryRecord:
    """One saved demo crop observation kept separate from real discoveries."""

    id: str
    saved_at: float
    crop_path: Path
    crop_hash: str
    width: int
    height: int
    confidence: float
    species_id: str
    common_name: str
    scientific_name: str
    family: str
    category: str
    conservation_status: str
    classifier_version: str
    sources: tuple[str, ...]
    is_stub: bool = True
    demo_label: str = DEMO_DATA_LABEL
    short_notes: str | None = None

    @property
    def crop_filename(self) -> str:
        return self.crop_path.name

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "saved_at": self.saved_at,
            "crop_path": str(self.crop_path),
            "crop_filename": self.crop_filename,
            "crop_hash": self.crop_hash,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
            "species_id": self.species_id,
            "common_name": self.common_name,
            "scientific_name": self.scientific_name,
            "family": self.family,
            "category": self.category,
            "conservation_status": self.conservation_status,
            "classifier_version": self.classifier_version,
            "sources": list(self.sources),
            "is_stub": self.is_stub,
            "demo_label": self.demo_label,
            "short_notes": self.short_notes,
        }

class DemoLibrary:
    """SQLite-backed demo save repository with crop-only file persistence."""

    def __init__(
        self,
        database_path: Path,
        media_dir: Path,
        *,
        deduplication_seconds: float = 5.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if deduplication_seconds < 0:
            raise ValueError("deduplication_seconds must not be negative")
        self.database_path = database_path
        self.media_dir = media_dir
        self.deduplication_seconds = deduplication_seconds
        self._clock = clock
        self._connection: sqlite3.Connection | None = None
        # The connection is shared across request-worker threads; every use is
        # serialised through this reentrant lock.
        self._db_lock = threading.RLock()
        self.migrate()

    def _connect(self) -> sqlite3.Connection:
        with self._db_lock:
            if self._connection is None:
                self.database_path.parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(
                    str(self.database_path), check_same_thread=False
                )
                self._connection.row_factory = sqlite3.Row
                self._connection.execute("PRAGMA journal_mode=WAL")
            return self._connection

    def migrate(self) -> None:
        """Create the schema version marker and apply unapplied migrations."""

        with self._db_lock:
            connection = self._connect()
            connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS demo_saves (
                id TEXT PRIMARY KEY,
                saved_at REAL NOT NULL,
                crop_path TEXT NOT NULL,
                crop_hash TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                request_id TEXT NOT NULL,
                species_id TEXT NOT NULL,
                common_name TEXT NOT NULL,
                scientific_name TEXT NOT NULL,
                family TEXT NOT NULL,
                category TEXT NOT NULL,
                conservation_status TEXT NOT NULL,
                confidence REAL NOT NULL,
                classifier_version TEXT NOT NULL,
                is_stub INTEGER NOT NULL DEFAULT 1,
                demo_label TEXT NOT NULL DEFAULT 'DEMO DATA',
                short_notes TEXT,
                sources TEXT NOT NULL DEFAULT '[]'
            );
                CREATE INDEX IF NOT EXISTS idx_demo_saves_species
                    ON demo_saves(species_id);
            """
            )
            row = connection.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,)
                )
            connection.commit()

    def probe(self) -> str:
        """Return ``ok`` when the database and media directory are writable."""

        try:
            self.media_dir.mkdir(parents=True, exist_ok=True)
            probe_file = self.media_dir / ".write-probe"
            probe_file.write_text("ok", encoding="utf-8")
            probe_file.unlink()
            with self._db_lock:
                connection = self._connect()
                connection.execute("SELECT 1 FROM schema_version").fetchone()
                connection.rollback()
            return "ok"
        except (OSError, sqlite3.Error) as exc:
            return f"storage error: {exc}"

    def save(
        self,
        capture: CaptureResult,
        run: ClassificationRun,
        *,
        request_name: str = "scan",
    ) -> DemoLibraryRecord:
        """Persist one crop and its stub result in one recoverable transaction.

        The crop is copied to the managed media directory, verified, and only
        then committed as a database row.  Rapid accidental saves of the same
        crop within the deduplication window return the existing record instead.
        """

        if capture.path is None:
            raise ValueError("cannot save a capture without a crop file")
        result = run.result
        if not result.is_accepted:
            raise ValueError("only accepted stub results may be saved")
        if not result.is_stub:
            raise ValueError("Phase 5 cannot save production results; wait for Phase 6")

        duplicate = self._find_recent_duplicate(capture.content_hash)
        if duplicate is not None:
            return duplicate

        now = self._clock()
        self.media_dir.mkdir(parents=True, exist_ok=True)
        destination = self.media_dir / f"crop-{int(now * 1000)}-{capture.content_hash[:12]}.png"
        shutil.copyfile(capture.path, destination)
        if not destination.is_file() or destination.stat().st_size <= 0:
            destination.unlink(missing_ok=True)
            raise OSError("crop copy could not be verified before commit")

        record = DemoLibraryRecord(
            id=uuid.uuid4().hex,
            saved_at=now,
            crop_path=destination.resolve(),
            crop_hash=capture.content_hash,
            width=capture.width,
            height=capture.height,
            confidence=float(result.confidence or 0.0),
            species_id=result.species_id or "",
            common_name=result.common_name or "",
            scientific_name=result.scientific_name or "",
            family=result.family or "",
            category=result.category or "",
            conservation_status=result.conservation_status or "",
            classifier_version=result.classifier_version,
            sources=result.sources,
            is_stub=True,
            demo_label=DEMO_DATA_LABEL,
            short_notes=result.short_notes,
        )
        with self._db_lock:
            connection = self._connect()
            try:
                connection.execute(
                    """
                    INSERT INTO demo_saves (
                        id, saved_at, crop_path, crop_hash, width, height, request_id,
                        species_id, common_name, scientific_name, family, category,
                        conservation_status, confidence, classifier_version, is_stub,
                        demo_label, short_notes, sources
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        record.id,
                        record.saved_at,
                        str(record.crop_path),
                        record.crop_hash,
                        record.width,
                        record.height,
                        request_name,
                        record.species_id,
                        record.common_name,
                        record.scientific_name,
                        record.family,
                        record.category,
                        record.conservation_status,
                        record.confidence,
                        record.classifier_version,
                        record.demo_label,
                        record.short_notes,
                        json.dumps(list(record.sources)),
                    ),
                )
                connection.commit()
            except sqlite3.Error:
                # The row was not committed, so the copied file is an orphan.
                destination.unlink(missing_ok=True)
                raise
        return record

    def list_records(self) -> list[DemoLibraryRecord]:
        with self._db_lock:
            rows = self._connect().execute(
                "SELECT * FROM demo_saves ORDER BY saved_at DESC"
            ).fetchall()
        return [_record_from_row(row) for row in rows]

    def get(self, record_id: str) -> DemoLibraryRecord | None:
        with self._db_lock:
            row = self._connect().execute(
                "SELECT * FROM demo_saves WHERE id = ?", (record_id,)
            ).fetchone()
        return _record_from_row(row) if row is not None else None

    def delete(self, record_id: str, *, confirmed: bool = False) -> bool:
        """Delete a demo record and its crop file only after confirmation."""

        if not confirmed:
            raise ValueError("deleting a library record requires explicit confirmation")
        record = self.get(record_id)
        if record is None:
            return False
        with self._db_lock:
            connection = self._connect()
            connection.execute("DELETE FROM demo_saves WHERE id = ?", (record_id,))
            connection.commit()
        try:
            Path(record.crop_path).unlink(missing_ok=True)
        except OSError:
            # A missing media file must not undo the confirmed database delete.
            pass
        return True

    def clear(self) -> int:
        """Remove every demo record; used by tests and explicit operator reset."""

        records = self.list_records()
        with self._db_lock:
            connection = self._connect()
            connection.execute("DELETE FROM demo_saves")
            connection.commit()
        for record in records:
            Path(record.crop_path).unlink(missing_ok=True)
        return len(records)

    def close(self) -> None:
        with self._db_lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _find_recent_duplicate(self, crop_hash: str) -> DemoLibraryRecord | None:
        now = self._clock()
        with self._db_lock:
            row = self._connect().execute(
                "SELECT * FROM demo_saves WHERE crop_hash = ? ORDER BY saved_at DESC LIMIT 1",
                (crop_hash,),
            ).fetchone()
        if row is None or now - float(row["saved_at"]) > self.deduplication_seconds:
            return None
        return _record_from_row(row)


def _record_from_row(row: sqlite3.Row) -> DemoLibraryRecord:
    return DemoLibraryRecord(
        id=str(row["id"]),
        saved_at=float(row["saved_at"]),
        crop_path=Path(str(row["crop_path"])),
        crop_hash=str(row["crop_hash"]),
        width=int(row["width"]),
        height=int(row["height"]),
        confidence=float(row["confidence"]),
        species_id=str(row["species_id"]),
        common_name=str(row["common_name"]),
        scientific_name=str(row["scientific_name"]),
        family=str(row["family"]),
        category=str(row["category"]),
        conservation_status=str(row["conservation_status"]),
        classifier_version=str(row["classifier_version"]),
        sources=tuple(json.loads(str(row["sources"]))),
        is_stub=bool(int(row["is_stub"])),
        demo_label=str(row["demo_label"]),
        short_notes=(row["short_notes"] or None),
    )
