"""Authoritative SQLite and filesystem persistence for Botanika."""

from .database import DATABASE_SCHEMA_VERSION, DatabaseError, SQLiteDatabase
from .discoveries import DiscoveryError, DiscoveryLibrary, LibraryRecord
from .library import DemoLibrary, DemoLibraryRecord, SCHEMA_VERSION

__all__ = [
    "DemoLibrary",
    "DemoLibraryRecord",
    "DiscoveryError",
    "DiscoveryLibrary",
    "LibraryRecord",
    "DATABASE_SCHEMA_VERSION",
    "DatabaseError",
    "SCHEMA_VERSION",
    "SQLiteDatabase",
]
