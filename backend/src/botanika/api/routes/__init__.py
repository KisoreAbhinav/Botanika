"""Versioned local API routes for the Phase 6 modular monolith."""

from .capabilities import router as capabilities_router
from .health import router as health_router
from .library import router as library_router
from .scan import router as scan_router
from .species import router as species_router

__all__ = [
    "capabilities_router",
    "health_router",
    "library_router",
    "scan_router",
    "species_router",
]
