"""Shared SQLite lifecycle and schema migrations for the Botanika runtime.

The application deliberately keeps SQLite small and boring.  A single
connection is used by each repository and all writes are serialized through a
re-entrant lock.  The schema is created by numbered migrations so a Pi can be
upgraded without throwing away its discovery library.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import threading
from typing import Iterator


DATABASE_SCHEMA_VERSION = 4


def utc_now() -> str:
    """Return a sortable, timezone-aware UTC timestamp for metadata rows."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DatabaseError(RuntimeError):
    """Raised when the local structured store cannot be opened or migrated."""


class SQLiteDatabase:
    """Thread-safe SQLite connection with an explicit migration boundary."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self.migrate()

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    connection = sqlite3.connect(
                        str(self.path),
                        check_same_thread=False,
                        timeout=10.0,
                    )
                    connection.row_factory = sqlite3.Row
                    connection.execute("PRAGMA foreign_keys = ON")
                    connection.execute("PRAGMA journal_mode = WAL")
                    connection.execute("PRAGMA synchronous = NORMAL")
                    self._connection = connection
                except sqlite3.Error as exc:
                    raise DatabaseError(f"could not open SQLite database: {exc}") from exc
            return self._connection

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        """Run one serialized transaction and roll it back on every failure."""

        with self._lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def migrate(self) -> None:
        """Apply all known migrations exactly once."""

        with self._lock:
            connection = self.connect()
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS botanika_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )
            applied = {
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM botanika_migrations"
                ).fetchall()
            }
            if 1 not in applied:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS catalog_metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS species (
                        species_id TEXT PRIMARY KEY,
                        scientific_name TEXT NOT NULL,
                        common_name TEXT NOT NULL,
                        family TEXT NOT NULL,
                        region TEXT NOT NULL,
                        category TEXT NOT NULL,
                        native_status TEXT NOT NULL,
                        is_native INTEGER NOT NULL DEFAULT 0 CHECK (is_native IN (0, 1)),
                        conservation_status TEXT NOT NULL,
                        ecology TEXT NOT NULL,
                        short_notes TEXT NOT NULL,
                        image_views TEXT NOT NULL DEFAULT '[]',
                        active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS species_aliases (
                        alias_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        species_id TEXT NOT NULL REFERENCES species(species_id) ON DELETE CASCADE,
                        alias TEXT NOT NULL,
                        normalized_alias TEXT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'common',
                        UNIQUE(species_id, normalized_alias)
                    );
                    CREATE INDEX IF NOT EXISTS idx_species_alias_normalized
                        ON species_aliases(normalized_alias);

                    CREATE TABLE IF NOT EXISTS species_categories (
                        species_id TEXT NOT NULL REFERENCES species(species_id) ON DELETE CASCADE,
                        category TEXT NOT NULL,
                        region TEXT NOT NULL,
                        is_native INTEGER NOT NULL DEFAULT 0 CHECK (is_native IN (0, 1)),
                        PRIMARY KEY(species_id, category, region)
                    );

                    CREATE TABLE IF NOT EXISTS sources (
                        source_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        publisher TEXT NOT NULL,
                        url TEXT NOT NULL,
                        license TEXT NOT NULL,
                        license_url TEXT,
                        retrieved_at TEXT,
                        checksum TEXT,
                        source_type TEXT NOT NULL DEFAULT 'reference'
                    );

                    CREATE TABLE IF NOT EXISTS species_sources (
                        species_id TEXT NOT NULL REFERENCES species(species_id) ON DELETE CASCADE,
                        source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
                        role TEXT NOT NULL,
                        PRIMARY KEY(species_id, source_id, role)
                    );

                    CREATE TABLE IF NOT EXISTS conservation_assessments (
                        assessment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        species_id TEXT NOT NULL REFERENCES species(species_id) ON DELETE CASCADE,
                        authority TEXT NOT NULL,
                        status TEXT NOT NULL,
                        assessment_url TEXT,
                        assessed_at TEXT,
                        notes TEXT,
                        UNIQUE(species_id, authority)
                    );

                    CREATE TABLE IF NOT EXISTS ecology_notes (
                        note_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        species_id TEXT NOT NULL REFERENCES species(species_id) ON DELETE CASCADE,
                        note TEXT NOT NULL,
                        source_id TEXT REFERENCES sources(source_id) ON DELETE RESTRICT,
                        UNIQUE(species_id, note)
                    );

                    CREATE TABLE IF NOT EXISTS knowledge_chunks (
                        chunk_id TEXT PRIMARY KEY,
                        species_id TEXT REFERENCES species(species_id) ON DELETE CASCADE,
                        source_id TEXT NOT NULL REFERENCES sources(source_id) ON DELETE RESTRICT,
                        chunk_index INTEGER NOT NULL,
                        content TEXT NOT NULL,
                        embedding_ref TEXT,
                        checksum TEXT NOT NULL,
                        UNIQUE(source_id, chunk_index, species_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_knowledge_species
                        ON knowledge_chunks(species_id);

                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
                        chunk_id UNINDEXED,
                        species_id UNINDEXED,
                        content
                    );

                    CREATE TABLE IF NOT EXISTS model_releases (
                        release_id TEXT PRIMARY KEY,
                        model_id TEXT NOT NULL,
                        version TEXT NOT NULL UNIQUE,
                        artifact_path TEXT NOT NULL,
                        artifact_sha256 TEXT NOT NULL,
                        runtime TEXT NOT NULL,
                        label_map TEXT NOT NULL,
                        preprocessing TEXT NOT NULL,
                        metrics TEXT NOT NULL,
                        calibration TEXT NOT NULL,
                        dataset_provenance TEXT NOT NULL,
                        supported_region TEXT NOT NULL,
                        active INTEGER NOT NULL DEFAULT 0 CHECK (active IN (0, 1)),
                        created_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS library_species (
                        species_id TEXT PRIMARY KEY REFERENCES species(species_id) ON DELETE RESTRICT,
                        first_seen REAL NOT NULL,
                        last_seen REAL NOT NULL,
                        observation_count INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS discoveries (
                        observation_id TEXT PRIMARY KEY,
                        species_id TEXT NOT NULL REFERENCES species(species_id) ON DELETE RESTRICT,
                        observed_at REAL NOT NULL,
                        saved_at REAL NOT NULL,
                        confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                        classifier_version TEXT NOT NULL,
                        request_id TEXT NOT NULL,
                        result_snapshot TEXT NOT NULL,
                        note TEXT,
                        deleted_at REAL
                    );
                    CREATE INDEX IF NOT EXISTS idx_discoveries_species_time
                        ON discoveries(species_id, observed_at DESC);

                    CREATE TABLE IF NOT EXISTS discovery_images (
                        image_id TEXT PRIMARY KEY,
                        observation_id TEXT NOT NULL REFERENCES discoveries(observation_id) ON DELETE CASCADE,
                        crop_path TEXT NOT NULL UNIQUE,
                        thumbnail_path TEXT,
                        crop_hash TEXT NOT NULL,
                        width INTEGER NOT NULL,
                        height INTEGER NOT NULL,
                        mime_type TEXT NOT NULL,
                        byte_size INTEGER NOT NULL,
                        created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_discovery_images_hash
                        ON discovery_images(crop_hash);

                    CREATE TABLE IF NOT EXISTS positioning_samples (
                        sample_id TEXT PRIMARY KEY,
                        observation_id TEXT REFERENCES discoveries(observation_id) ON DELETE CASCADE,
                        latitude REAL NOT NULL,
                        longitude REAL NOT NULL,
                        accuracy_m REAL NOT NULL,
                        source TEXT NOT NULL,
                        captured_at REAL NOT NULL,
                        CHECK(latitude >= -90 AND latitude <= 90),
                        CHECK(longitude >= -180 AND longitude <= 180),
                        CHECK(accuracy_m >= 0)
                    );

                    CREATE TABLE IF NOT EXISTS weed_observations (
                        observation_id TEXT PRIMARY KEY,
                        latitude REAL,
                        longitude REAL,
                        accuracy_m REAL,
                        position_source TEXT,
                        observed_at REAL NOT NULL,
                        detector_version TEXT NOT NULL,
                        weed_class TEXT NOT NULL,
                        confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1)
                    );
                    """
                )
                connection.execute(
                    "INSERT INTO botanika_migrations(version, applied_at) VALUES (?, ?)",
                    (1, utc_now()),
                )
            if 2 not in applied:
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(species)").fetchall()
                }
                if "is_native" not in columns:
                    connection.execute(
                        "ALTER TABLE species ADD COLUMN is_native INTEGER NOT NULL DEFAULT 0"
                    )
                connection.execute(
                    "INSERT INTO botanika_migrations(version, applied_at) VALUES (?, ?)",
                    (2, utc_now()),
                )
            if 3 not in applied:
                connection.executescript(
                    """
                    -- The vector index is deliberately compact and local.  The
                    -- embedding bytes are deterministic, versioned, and tied
                    -- to each reviewed knowledge chunk checksum.
                    CREATE TABLE IF NOT EXISTS knowledge_embeddings (
                        chunk_id TEXT PRIMARY KEY REFERENCES knowledge_chunks(chunk_id) ON DELETE CASCADE,
                        embedding_version TEXT NOT NULL,
                        dimensions INTEGER NOT NULL CHECK (dimensions > 0),
                        vector BLOB NOT NULL,
                        checksum TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_version
                        ON knowledge_embeddings(embedding_version);

                    CREATE TABLE IF NOT EXISTS knowledge_ingestion (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS weed_runs (
                        run_id TEXT PRIMARY KEY,
                        observed_at REAL NOT NULL,
                        detector_version TEXT NOT NULL,
                        crop_context TEXT NOT NULL,
                        position_available INTEGER NOT NULL DEFAULT 0 CHECK (position_available IN (0, 1)),
                        position_message TEXT NOT NULL,
                        detections_json TEXT NOT NULL DEFAULT '[]',
                        model_metadata TEXT NOT NULL DEFAULT '{}'
                    );
                    CREATE TABLE IF NOT EXISTS weed_observations (
                        observation_id TEXT PRIMARY KEY,
                        latitude REAL,
                        longitude REAL,
                        accuracy_m REAL,
                        position_source TEXT,
                        observed_at REAL NOT NULL,
                        detector_version TEXT NOT NULL,
                        weed_class TEXT NOT NULL,
                        confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1)
                    );
                    """
                )
                weed_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(weed_observations)").fetchall()
                }
                for column, definition in (
                    ("run_id", "TEXT"),
                    ("model_metadata", "TEXT NOT NULL DEFAULT '{}'"),
                    ("position_timestamp", "REAL"),
                ):
                    if column not in weed_columns:
                        connection.execute(
                            f"ALTER TABLE weed_observations ADD COLUMN {column} {definition}"
                        )
                run_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(weed_runs)").fetchall()
                }
                for column, definition in (
                    ("detections_json", "TEXT NOT NULL DEFAULT '[]'"),
                    ("model_metadata", "TEXT NOT NULL DEFAULT '{}'"),
                ):
                    if column not in run_columns:
                        connection.execute(
                            f"ALTER TABLE weed_runs ADD COLUMN {column} {definition}"
                        )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_weed_observations_run "
                    "ON weed_observations(run_id)"
                )
                connection.execute(
                    "INSERT INTO botanika_migrations(version, applied_at) VALUES (?, ?)",
                    (3, utc_now()),
                )
            if 4 not in applied:
                run_columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(weed_runs)").fetchall()
                }
                for column, definition in (
                    ("detections_json", "TEXT NOT NULL DEFAULT '[]'"),
                    ("model_metadata", "TEXT NOT NULL DEFAULT '{}'"),
                ):
                    if column not in run_columns:
                        connection.execute(
                            f"ALTER TABLE weed_runs ADD COLUMN {column} {definition}"
                        )
                connection.execute(
                    "INSERT INTO botanika_migrations(version, applied_at) VALUES (?, ?)",
                    (4, utc_now()),
                )
            connection.commit()

    def backup_to(self, destination: Path) -> None:
        """Create a consistent SQLite backup without copying a live WAL file."""

        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            source = self.connect()
            target = sqlite3.connect(str(destination))
            try:
                source.backup(target)
            finally:
                target.close()

    def restore_from(self, source_path: Path) -> None:
        """Replace database contents through SQLite's online backup API.

        Keeping the connection object alive matters because the knowledge and
        discovery repositories may share this database while the service is
        running.
        """

        with self._lock:
            source = sqlite3.connect(str(source_path))
            try:
                source.backup(self.connect())
            finally:
                source.close()

    def probe(self) -> str:
        try:
            with self._lock:
                self.connect().execute("SELECT 1").fetchone()
            return "ok"
        except (DatabaseError, sqlite3.Error, OSError) as exc:
            return f"storage error: {exc}"

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
