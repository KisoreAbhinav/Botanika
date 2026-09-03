"""Shared settings for the Botanika Phase 6 local application."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
DEFAULT_MANIFEST = PROJECT_ROOT / "config" / "models" / "yolo11n-coco.json"
DEFAULT_QUALITY_CONFIG = PROJECT_ROOT / "config" / "vision" / "phase3-quality-baseline.json"
DEFAULT_SPECIES_CATALOG = PROJECT_ROOT / "config" / "catalog" / "india-starter-species.json"
DEFAULT_CLASSIFIER_MODEL = PROJECT_ROOT / "models" / "plant_classifier" / "india-starter-feature-v1.json"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
DEFAULT_SQLITE_PATH = PROJECT_ROOT / "data" / "database" / "botanika.sqlite"


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Validated local-only configuration for the modular monolith.

    The service intentionally binds to loopback only through Phase 6.  Paths
    are resolved eagerly so a misconfigured layout fails at startup instead of
    during a request.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    loopback_only: bool = True

    # Vision pipeline
    manifest_path: Path = DEFAULT_MANIFEST
    quality_config_path: Path = DEFAULT_QUALITY_CONFIG
    eligible_labels: frozenset[str] = field(default_factory=lambda: frozenset({"potted plant"}))
    detector_confidence: float = 0.25
    detector_nms_iou: float = 0.45
    stable_checks: int = 4
    appearance_similarity: float = 0.70
    cooldown_frames: int = 30
    crop_padding_ratio: float = 0.08

    # Phase 6 catalog/model release. The artifact is loaded once by the scan
    # owner; a missing or invalid artifact is an honest unavailable state.
    species_catalog_path: Path = DEFAULT_SPECIES_CATALOG
    classifier_model_path: Path = DEFAULT_CLASSIFIER_MODEL
    acceptance_threshold: float = 0.62

    # Preview stream contract shared with the kiosk overlay.
    preview_width: int = 500
    preview_height: int = 330
    preview_jpeg_quality: int = 72
    max_fallback_upload_bytes: int = 12 * 1024 * 1024

    # Managed runtime data
    database_path: Path = DEFAULT_SQLITE_PATH
    temp_crops_dir: Path = PROJECT_ROOT / "data" / "media" / "temp" / "phase6-crops"
    discoveries_dir: Path | None = None
    backup_dir: Path = PROJECT_ROOT / "data" / "backups"
    library_quota_bytes: int = 2 * 1024 * 1024 * 1024
    library_quota_observations: int = 10000

    max_consecutive_drops: int = 30
    event_backlog: int = 50
    request_log_limit: int = 200
    save_deduplication_seconds: float = 5.0
    # Compatibility fields for Phase 5 tests/config callers. New runtime code
    # uses discoveries_dir and save_deduplication_seconds.
    demo_discoveries_dir: Path = PROJECT_ROOT / "data" / "media" / "discoveries" / "demo"
    demo_save_deduplication_seconds: float = 5.0
    legacy_demo_mode: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        legacy_demo_mode = self.discoveries_dir is None and (
            self.demo_discoveries_dir
            != PROJECT_ROOT / "data" / "media" / "discoveries" / "demo"
        )
        object.__setattr__(self, "legacy_demo_mode", legacy_demo_mode)
        if self.discoveries_dir is None:
            # Phase 5 callers passed only demo_discoveries_dir. Honour that
            # explicit temporary location while the new default stays real.
            resolved_discoveries = (
                self.demo_discoveries_dir
                if self.demo_discoveries_dir != PROJECT_ROOT / "data" / "media" / "discoveries" / "demo"
                else PROJECT_ROOT / "data" / "media" / "discoveries" / "real"
            )
            object.__setattr__(self, "discoveries_dir", resolved_discoveries)
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if self.loopback_only and self.host != "127.0.0.1":
            raise ValueError("Phase 6 must keep the service on loopback (127.0.0.1)")
        if self.preview_width <= 0 or self.preview_height <= 0:
            raise ValueError("preview dimensions must be positive")
        if self.max_fallback_upload_bytes <= 0:
            raise ValueError("fallback upload limit must be positive")
        if self.library_quota_bytes <= 0 or self.library_quota_observations <= 0:
            raise ValueError("library quotas must be positive")
        if self.save_deduplication_seconds < 0 or self.demo_save_deduplication_seconds < 0:
            raise ValueError("deduplication windows must not be negative")
        if self.stable_checks < 2:
            raise ValueError("stable_checks must be at least 2")
        for label in self.eligible_labels:
            if not isinstance(label, str) or not label.strip():
                raise ValueError("eligible_labels must contain non-empty strings")
