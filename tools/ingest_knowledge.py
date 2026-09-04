#!/usr/bin/env python3
"""Rebuild Botanika's offline FTS/vector knowledge index from reviewed files.

This tool is intentionally offline. It reads the versioned catalog and its
source/license manifest, seeds SQLite, verifies that provenance agrees, and
optionally writes the resulting stable chunk manifest for release evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import DEFAULT_SPECIES_CATALOG, DEFAULT_SQLITE_PATH
from botanika.knowledge import KnowledgeStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_SQLITE_PATH)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_SPECIES_CATALOG)
    parser.add_argument(
        "--source-license-manifest",
        type=Path,
        default=PROJECT_ROOT / "config" / "knowledge" / "source-license-manifest.json",
    )
    parser.add_argument("--manifest-output", type=Path, default=None)
    parser.add_argument("--check", action="store_true", help="validate provenance without writing an output manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source_manifest = json.loads(args.source_license_manifest.read_text(encoding="utf-8"))
        catalog_bytes = args.catalog.read_bytes()
        if source_manifest.get("catalog_sha256") != hashlib.sha256(catalog_bytes).hexdigest():
            raise ValueError("source/license manifest catalog_sha256 does not match the catalog")
        expected = {
            str(item["source_id"]): (str(item.get("license", "")), str(item.get("url", "")))
            for item in source_manifest.get("sources", [])
        }
        store = KnowledgeStore(args.database, args.catalog)
        try:
            actual = store.knowledge_manifest()
            actual_sources = {
                str(item["source_id"]): (str(item.get("license", "")), str(item.get("url", "")))
                for item in actual["sources"]
            }
            if expected != actual_sources:
                raise ValueError("source/license manifest does not match the seeded catalog sources")
            if args.manifest_output is not None and not args.check:
                args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
                args.manifest_output.write_text(
                    json.dumps(actual, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            result = {
                "status": "ok",
                "database": str(args.database),
                "catalog": str(args.catalog),
                "ingestion": store.ingestion_status(),
                "manifest_digest": actual["manifest_digest"],
                "source_count": len(actual["sources"]),
                "chunk_count": len(actual["chunks"]),
            }
        finally:
            store.close()
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "detail": str(exc)}))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
