"""Offline species facts, exact search, and citation-producing retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import struct
from typing import Any, Iterable
import uuid

from botanika.storage.database import SQLiteDatabase, utc_now

from .catalog import CatalogDefinition, CatalogIntegrityError, SpeciesRecord, load_catalog, normalize_name
from .embeddings import (
    DEFAULT_DIMENSIONS,
    EMBEDDING_VERSION,
    cosine,
    embed,
    pack,
    unpack,
)


ABSTENTION = "I could not find enough reliable offline information to answer that."


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    chunk_id: str
    species_id: str | None
    content: str
    source_id: str
    source_title: str
    source_url: str
    source_license: str
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "species_id": self.species_id,
            "content": self.content,
            "score": self.score,
            "source": {
                "source_id": self.source_id,
                "title": self.source_title,
                "url": self.source_url,
                "license": self.source_license,
            },
        }


@dataclass(frozen=True, slots=True)
class GroundedAnswer:
    answer: str
    citations: tuple[KnowledgeHit, ...]
    evidence: tuple[KnowledgeHit, ...]
    abstained: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": [item.to_dict() for item in self.citations],
            "evidence": [item.to_dict() for item in self.evidence],
            "abstained": self.abstained,
        }


class KnowledgeStore:
    """SQLite-backed, provenance-first catalog and FTS5 knowledge store."""

    def __init__(self, database_path: Path, catalog_path: Path, *, seed: bool = True) -> None:
        self.database = SQLiteDatabase(Path(database_path))
        try:
            self.catalog_path = Path(catalog_path)
            self.catalog: CatalogDefinition = load_catalog(self.catalog_path)
            if seed:
                self.seed_catalog()
        except Exception:
            self.database.close()
            raise

    @property
    def database_path(self) -> Path:
        return self.database.path

    @property
    def catalog_version(self) -> str:
        return self.catalog.version

    @property
    def catalog_digest(self) -> str:
        return self.catalog.digest

    def seed_catalog(self) -> None:
        """Insert the immutable seed and reject silent catalog drift."""

        # A restore may come from a pre-Phase-9 database.  Re-run the schema
        # boundary before rebuilding the knowledge index so upgrades remain
        # safe and deterministic.
        self.database.migrate()
        now = utc_now()
        with self.database.transaction() as connection:
            existing_meta = {
                row["key"]: row["value"]
                for row in connection.execute("SELECT key, value FROM catalog_metadata")
            }
            stored_digest = existing_meta.get("catalog_digest")
            stored_version = existing_meta.get("catalog_version")
            if (
                stored_digest
                and stored_digest != self.catalog.digest
                and stored_version == self.catalog.version
            ):
                raise CatalogIntegrityError(
                    "catalog digest changed without a catalog version bump"
                )
            connection.executemany(
                """
                INSERT INTO sources(
                    source_id, title, publisher, url, license, license_url,
                    retrieved_at, checksum, source_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title=excluded.title, publisher=excluded.publisher, url=excluded.url,
                    license=excluded.license, license_url=excluded.license_url,
                    retrieved_at=excluded.retrieved_at, checksum=excluded.checksum,
                    source_type=excluded.source_type
                """,
                [
                    (
                        source.source_id, source.title, source.publisher, source.url,
                        source.license, source.license_url, source.retrieved_at,
                        source.checksum, source.source_type,
                    )
                    for source in self.catalog.sources
                ],
            )
            # Knowledge chunks and ecology notes are immutable catalog seed
            # material rather than user content. Rebuild them on an explicitly
            # versioned catalog revision so retired source URLs cannot survive
            # in FTS results after an upgrade.
            connection.execute("DELETE FROM ecology_notes")
            connection.execute("DELETE FROM knowledge_chunks")
            for species in self.catalog.species:
                row = connection.execute(
                    "SELECT * FROM species WHERE species_id = ?", (species.species_id,)
                ).fetchone()
                values = (
                    species.species_id, species.scientific_name, species.common_name,
                    species.family, species.region, species.category, species.native_status,
                    int(species.is_native), species.conservation_status, species.ecology, species.short_notes,
                    json.dumps(list(species.image_views)), now, now,
                )
                if row is not None:
                    expected = {
                        "scientific_name": species.scientific_name,
                        "common_name": species.common_name,
                        "family": species.family,
                        "region": species.region,
                        "category": species.category,
                        "native_status": species.native_status,
                        "is_native": str(int(species.is_native)),
                        "conservation_status": species.conservation_status,
                        "ecology": species.ecology,
                        "short_notes": species.short_notes,
                    }
                    if any(str(row[key]) != value for key, value in expected.items()):
                        raise CatalogIntegrityError(
                            f"stable species metadata changed for {species.species_id}"
                        )
                else:
                    connection.execute(
                        """
                        INSERT INTO species(
                            species_id, scientific_name, common_name, family, region,
                            category, native_status, is_native, conservation_status,
                            ecology, short_notes, image_views, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        values,
                    )
                connection.executemany(
                    """
                    INSERT OR IGNORE INTO species_aliases(
                        species_id, alias, normalized_alias, kind
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [
                        (species.species_id, name, normalize_name(name), "common")
                        for name in (species.common_name, species.scientific_name, *species.aliases)
                    ],
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO species_categories(species_id, category, region, is_native)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        species.species_id,
                        species.category,
                        species.region,
                        int(species.is_native),
                    ),
                )
                for source_id in species.source_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO species_sources(species_id, source_id, role) VALUES (?, ?, ?)",
                        (species.species_id, source_id, "catalog"),
                    )
                for source_id in species.image_source_ids:
                    connection.execute(
                        "INSERT OR IGNORE INTO species_sources(species_id, source_id, role) VALUES (?, ?, ?)",
                        (species.species_id, source_id, "image-reference"),
                    )
                for assessment in species.assessments:
                    connection.execute(
                        """
                        INSERT INTO conservation_assessments(
                            species_id, authority, status, assessment_url, assessed_at, notes
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(species_id, authority) DO UPDATE SET
                            status=excluded.status, assessment_url=excluded.assessment_url,
                            assessed_at=excluded.assessed_at, notes=excluded.notes
                        """,
                        (
                            species.species_id, assessment.authority, assessment.status,
                            assessment.assessment_url, assessment.assessed_at, assessment.notes,
                        ),
                    )
                source_chunk_indexes: dict[str, int] = {}
                for note in species.knowledge:
                    chunk_index = source_chunk_indexes.get(note.source_id, 0)
                    source_chunk_indexes[note.source_id] = chunk_index + 1
                    checksum = hashlib.sha256(note.text.encode("utf-8")).hexdigest()
                    chunk_id = f"{species.species_id}:{note.source_id}:{checksum[:16]}"
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO knowledge_chunks(
                            chunk_id, species_id, source_id, chunk_index, content,
                            embedding_ref, checksum
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk_id, species.species_id, note.source_id, chunk_index, note.text,
                            f"hash:{checksum[:16]}", checksum,
                        ),
                    )
                    if note.kind.lower() in {"ecology", "habitat"}:
                        connection.execute(
                            """
                            INSERT OR IGNORE INTO ecology_notes(species_id, note, source_id)
                            VALUES (?, ?, ?)
                            """,
                            (species.species_id, note.text, note.source_id),
                        )

            release = self.catalog.model_release
            connection.execute(
                """
                INSERT INTO model_releases(
                    release_id, model_id, version, artifact_path, artifact_sha256,
                    runtime, label_map, preprocessing, metrics, calibration,
                    dataset_provenance, supported_region, active, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(version) DO UPDATE SET
                    release_id=excluded.release_id, model_id=excluded.model_id,
                    artifact_path=excluded.artifact_path, artifact_sha256=excluded.artifact_sha256,
                    runtime=excluded.runtime, label_map=excluded.label_map,
                    preprocessing=excluded.preprocessing, metrics=excluded.metrics,
                    calibration=excluded.calibration, dataset_provenance=excluded.dataset_provenance,
                    supported_region=excluded.supported_region, active=excluded.active
                """,
                (
                    release.release_id, release.model_id, release.version,
                    release.artifact_path, release.artifact_sha256, release.runtime,
                    json.dumps(dict(release.label_map), sort_keys=True),
                    json.dumps(dict(release.preprocessing), sort_keys=True),
                    json.dumps(dict(release.metrics), sort_keys=True),
                    json.dumps(dict(release.calibration), sort_keys=True),
                    json.dumps(dict(release.dataset_provenance), sort_keys=True),
                    release.supported_region, int(release.active), now,
                ),
            )
            if release.active:
                connection.execute(
                    "UPDATE model_releases SET active = 0 WHERE version <> ?",
                    (release.version,),
                )
            connection.execute(
                "INSERT OR REPLACE INTO catalog_metadata(key, value) VALUES (?, ?)",
                ("catalog_id", self.catalog.catalog_id),
            )
            connection.execute(
                "INSERT OR REPLACE INTO catalog_metadata(key, value) VALUES (?, ?)",
                ("catalog_version", self.catalog.version),
            )
            connection.execute(
                "INSERT OR REPLACE INTO catalog_metadata(key, value) VALUES (?, ?)",
                ("catalog_region", self.catalog.region),
            )
            connection.execute(
                "INSERT OR REPLACE INTO catalog_metadata(key, value) VALUES (?, ?)",
                ("catalog_digest", self.catalog.digest),
            )
            connection.execute("DELETE FROM knowledge_fts")
            connection.execute(
                "INSERT INTO knowledge_fts(chunk_id, species_id, content) SELECT chunk_id, species_id, content FROM knowledge_chunks"
            )
            self._rebuild_embedding_index(connection, now)

    def _rebuild_embedding_index(self, connection, now: str) -> None:
        """Rebuild the compact index from the authoritative chunk rows."""

        connection.execute("DELETE FROM knowledge_embeddings")
        rows = connection.execute(
            "SELECT chunk_id, content, checksum FROM knowledge_chunks ORDER BY chunk_id"
        ).fetchall()
        connection.executemany(
            """
            INSERT INTO knowledge_embeddings(
                chunk_id, embedding_version, dimensions, vector, checksum, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    str(row["chunk_id"]),
                    EMBEDDING_VERSION,
                    DEFAULT_DIMENSIONS,
                    pack(embed(str(row["content"]), DEFAULT_DIMENSIONS)),
                    str(row["checksum"]),
                    now,
                )
                for row in rows
            ],
        )
        manifest = self._manifest_from_connection(connection)
        connection.execute("DELETE FROM knowledge_ingestion")
        connection.executemany(
            "INSERT INTO knowledge_ingestion(key, value) VALUES (?, ?)",
            [
                ("format", "botanika-knowledge-1"),
                ("embedding_version", EMBEDDING_VERSION),
                ("embedding_dimensions", str(DEFAULT_DIMENSIONS)),
                ("manifest_digest", manifest["manifest_digest"]),
                ("chunk_count", str(len(rows))),
                ("ingested_at", now),
            ],
        )

    def get_species(self, species_id: str) -> SpeciesRecord | None:
        return self.catalog.species_by_id().get(species_id)

    def list_species(self, *, query: str | None = None, category: str | None = None) -> list[SpeciesRecord]:
        values = list(self.catalog.species)
        if query:
            term = normalize_name(query)
            values = [
                item for item in values
                if term in normalize_name(item.common_name)
                or term in normalize_name(item.scientific_name)
                or any(term in normalize_name(alias) for alias in item.aliases)
            ]
        if category and category.lower() != "all":
            values = [item for item in values if item.category.lower() == category.lower()]
        return sorted(values, key=lambda item: item.common_name.lower())

    def source(self, source_id: str) -> dict[str, Any] | None:
        with self.database.transaction(immediate=False) as connection:
            row = connection.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,)).fetchone()
        return dict(row) if row is not None else None

    def search(
        self,
        query: str,
        *,
        species_id: str | None = None,
        limit: int = 5,
        use_embedding: bool = True,
    ) -> list[KnowledgeHit]:
        query = str(query or "").strip()
        if not query or limit <= 0:
            return []
        tokens = re.findall(r"[\w-]+", query.lower())
        if not tokens:
            return []
        fts_query = " AND ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        species_clause = " AND k.species_id = ?" if species_id is not None else ""
        with self.database.transaction(immediate=False) as connection:
            try:
                rows = connection.execute(
                    f"""
                    SELECT k.chunk_id, k.species_id, k.content, k.source_id,
                           s.title, s.url, s.license, bm25(knowledge_fts) AS rank
                    FROM knowledge_fts
                    JOIN knowledge_chunks k ON k.chunk_id = knowledge_fts.chunk_id
                    JOIN sources s ON s.source_id = k.source_id
                    WHERE knowledge_fts MATCH ?{species_clause}
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (
                        (fts_query, species_id, max(1, limit * 3))
                        if species_id is not None
                        else (fts_query, max(1, limit * 3))
                    ),
                ).fetchall()
            except Exception:
                rows = []
            if not rows:
                pattern = f"%{query}%"
                rows = connection.execute(
                    f"""
                    SELECT k.chunk_id, k.species_id, k.content, k.source_id,
                           s.title, s.url, s.license, 0.0 AS rank
                    FROM knowledge_chunks k
                    JOIN sources s ON s.source_id = k.source_id
                    WHERE lower(k.content) LIKE lower(?){species_clause}
                    ORDER BY k.chunk_id
                    LIMIT ?
                    """,
                    (
                        (pattern, species_id, limit * 3)
                        if species_id is not None
                        else (pattern, limit * 3)
                    ),
                ).fetchall()
        hits = [
            KnowledgeHit(
                chunk_id=str(row["chunk_id"]),
                species_id=str(row["species_id"]) if row["species_id"] is not None else None,
                content=str(row["content"]),
                source_id=str(row["source_id"]),
                source_title=str(row["title"]),
                source_url=str(row["url"]),
                source_license=str(row["license"]),
                score=1.0 / (1.0 + max(0.0, float(row["rank"]))),
            )
            for row in rows
            if species_id is None or str(row["species_id"]) == species_id
        ]
        if hits:
            return hits[:limit]

        # FTS remains the primary path.  The compact index is a bounded,
        # local lexical similarity fallback, and its threshold deliberately
        # favours abstention over a weak match.
        return self.embedding_search(query, species_id=species_id, limit=limit) if use_embedding else []

    def embedding_search(
        self,
        query: str,
        *,
        species_id: str | None = None,
        limit: int = 5,
        minimum_score: float = 0.24,
    ) -> list[KnowledgeHit]:
        """Search the deterministic compact index and preserve citations."""

        query = str(query or "").strip()
        if not query or limit <= 0:
            return []
        query_vector = embed(query, DEFAULT_DIMENSIONS)
        clause = " AND k.species_id = ?" if species_id is not None else ""
        params: tuple[object, ...] = (species_id,) if species_id is not None else ()
        with self.database.transaction(immediate=False) as connection:
            rows = connection.execute(
                f"""
                SELECT e.chunk_id, e.dimensions, e.vector, k.species_id, k.content,
                       k.source_id, s.title, s.url, s.license
                FROM knowledge_embeddings e
                JOIN knowledge_chunks k ON k.chunk_id = e.chunk_id
                JOIN sources s ON s.source_id = k.source_id
                WHERE e.embedding_version = ?{clause}
                """,
                (EMBEDDING_VERSION, *params),
            ).fetchall()
        ranked: list[tuple[float, object]] = []
        for row in rows:
            try:
                score = cosine(query_vector, unpack(row["vector"], int(row["dimensions"])))
            except (TypeError, ValueError, struct.error):
                continue
            if score >= minimum_score:
                ranked.append((score, row))
        ranked.sort(key=lambda item: (-item[0], str(item[1]["chunk_id"])))
        return [
            KnowledgeHit(
                chunk_id=str(row["chunk_id"]),
                species_id=str(row["species_id"]) if row["species_id"] is not None else None,
                content=str(row["content"]),
                source_id=str(row["source_id"]),
                source_title=str(row["title"]),
                source_url=str(row["url"]),
                source_license=str(row["license"]),
                score=float(score),
            )
            for score, row in ranked[:limit]
        ]

    def knowledge_manifest(self) -> dict[str, Any]:
        """Return a stable source/chunk/license manifest for diagnostics."""

        with self.database.transaction(immediate=False) as connection:
            return self._manifest_from_connection(connection)

    def ingestion_status(self) -> dict[str, Any]:
        with self.database.transaction(immediate=False) as connection:
            rows = connection.execute(
                "SELECT key, value FROM knowledge_ingestion ORDER BY key"
            ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    def _manifest_from_connection(self, connection) -> dict[str, Any]:
        sources = [
            {
                "source_id": str(row["source_id"]),
                "title": str(row["title"]),
                "publisher": str(row["publisher"]),
                "url": str(row["url"]),
                "license": str(row["license"]),
                "license_url": row["license_url"],
                "retrieved_at": row["retrieved_at"],
                "checksum": row["checksum"],
                "source_type": str(row["source_type"]),
            }
            for row in connection.execute(
                "SELECT source_id, title, publisher, url, license, license_url, "
                "retrieved_at, checksum, source_type FROM sources ORDER BY source_id"
            ).fetchall()
        ]
        chunks = [
            {
                "chunk_id": str(row["chunk_id"]),
                "species_id": row["species_id"],
                "source_id": str(row["source_id"]),
                "chunk_index": int(row["chunk_index"]),
                "checksum": str(row["checksum"]),
            }
            for row in connection.execute(
                "SELECT chunk_id, species_id, source_id, chunk_index, checksum "
                "FROM knowledge_chunks ORDER BY chunk_id"
            ).fetchall()
        ]
        value: dict[str, Any] = {
            "format": "botanika-knowledge-1",
            "catalog_id": self.catalog.catalog_id,
            "catalog_version": self.catalog.version,
            "catalog_region": self.catalog.region,
            "catalog_digest": self.catalog.digest,
            "embedding": {
                "version": EMBEDDING_VERSION,
                "dimensions": DEFAULT_DIMENSIONS,
                "algorithm": "sha256-signed-token-and-bigram-hashing",
            },
            "sources": sources,
            "chunks": chunks,
        }
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        value["manifest_digest"] = hashlib.sha256(canonical).hexdigest()
        return value

    def answer(self, query: str, *, context_species_id: str | None = None) -> GroundedAnswer:
        query = str(query or "").strip()
        if not query:
            return GroundedAnswer(ABSTENTION, (), (), True)
        context = self.get_species(context_species_id) if context_species_id else None
        # Generation/answering first uses exact reviewed retrieval.  The
        # compact embedding index remains available to search callers, but its
        # deliberately tiny hashing model must not turn an unrelated question
        # into a plausible-looking botanical answer.
        hits = (
            self.search(query, species_id=context_species_id, limit=4, use_embedding=False)
            if context_species_id
            else self.search(query, limit=4, use_embedding=False)
        )
        if not hits:
            resolved = self._resolve_species(query)
            if resolved is not None:
                hits = self.search(
                    resolved.species_id,
                    species_id=resolved.species_id,
                    limit=4,
                    use_embedding=False,
                )
                if not hits:
                    hits = self._species_facts(resolved.species_id, limit=4)
        if not hits and context is not None:
            hits = self._species_facts(context.species_id, limit=4)
        if not hits:
            return GroundedAnswer(ABSTENTION, (), (), True)
        # The Phase 6 guide is intentionally extractive: every sentence shown
        # is a reviewed local chunk, so there is no ungrounded LLM generation.
        answer = " ".join(hit.content for hit in hits[:2])
        return GroundedAnswer(answer, tuple(hits[:2]), tuple(hits), False)

    def _resolve_species(self, query: str) -> SpeciesRecord | None:
        normalized = normalize_name(query)
        for species in self.catalog.species:
            names = (species.common_name, species.scientific_name, *species.aliases)
            if any(normalize_name(name) in normalized or normalized in normalize_name(name) for name in names):
                return species
        return None

    def _species_facts(self, species_id: str, *, limit: int) -> list[KnowledgeHit]:
        with self.database.transaction(immediate=False) as connection:
            rows = connection.execute(
                """
                SELECT k.chunk_id, k.species_id, k.content, k.source_id,
                       s.title, s.url, s.license
                FROM knowledge_chunks k JOIN sources s ON s.source_id = k.source_id
                WHERE k.species_id = ? ORDER BY k.chunk_index, k.chunk_id LIMIT ?
                """,
                (species_id, limit),
            ).fetchall()
        return [
            KnowledgeHit(
                str(row["chunk_id"]), str(row["species_id"]), str(row["content"]),
                str(row["source_id"]), str(row["title"]), str(row["url"]),
                str(row["license"]), 1.0,
            )
            for row in rows
        ]

    def active_model_release(self) -> dict[str, Any] | None:
        with self.database.transaction(immediate=False) as connection:
            row = connection.execute(
                "SELECT * FROM model_releases WHERE active = 1 ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        value = dict(row)
        for key in ("label_map", "preprocessing", "metrics", "calibration", "dataset_provenance"):
            value[key] = json.loads(value[key])
        return value

    def probe(self) -> str:
        return self.database.probe()

    def close(self) -> None:
        self.database.close()


# A descriptive alias keeps imports pleasant for callers that think in terms
# of a catalog rather than a repository.
SpeciesCatalog = KnowledgeStore
