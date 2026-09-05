"""Authoritative SQLite and filesystem persistence for Botanika."""

from .database import DATABASE_SCHEMA_VERSION, DatabaseError, SQLiteDatabase
from .discoveries import CATEGORY_COLORS, DiscoveryError, DiscoveryLibrary, LibraryRecord, category_color
from .library import DemoLibrary, DemoLibraryRecord, SCHEMA_VERSION
from .weeds import NO_POSITION_MESSAGE, WeedObservationStore, WeedRunRecord

__all__ = [
    "DemoLibrary",
    "DemoLibraryRecord",
    "DiscoveryError",
    "DiscoveryLibrary",
    "LibraryRecord",
    "CATEGORY_COLORS",
    "category_color",
    "DATABASE_SCHEMA_VERSION",
    "DatabaseError",
    "SCHEMA_VERSION",
    "SQLiteDatabase",
    "NO_POSITION_MESSAGE",
    "WeedObservationStore",
    "WeedRunRecord",
]
