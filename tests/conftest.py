"""Test configuration for the source-layout Botanika package."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_SOURCE = Path(__file__).resolve().parents[1] / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

