"""Versioned local API routes for the Phase 9 modular monolith."""

from .capabilities import router as capabilities_router
from .health import router as health_router
from .library import router as library_router
from .mode import router as mode_router
from .network import router as network_router
from .scan import router as scan_router
from .species import router as species_router
from .voice import router as voice_router
from .weeds import router as weeds_router

__all__ = [
    "capabilities_router",
    "health_router",
    "library_router",
    "mode_router",
    "network_router",
    "scan_router",
    "species_router",
    "voice_router",
    "weeds_router",
]
