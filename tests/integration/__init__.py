"""Integration tests for multi-stage local pipelines."""

from pathlib import Path
import sys

BACKEND_SOURCE = Path(__file__).resolve().parents[2] / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))
