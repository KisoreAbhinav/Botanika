"""Runtime container shared by all API routes."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from botanika.core.capabilities import CapabilitiesReport, build_capabilities
from botanika.core.settings import AppSettings
from botanika.knowledge import KnowledgeStore
from botanika.observability import RequestLog
from botanika.storage import DemoLibrary, DiscoveryLibrary
from botanika.vision.services.scan import ScanService

APP_VERSION = "0.6.0"


@dataclass(slots=True)
class Runtime:
    """Long-lived application services owned by the FastAPI lifespan."""

    settings: AppSettings
    scan: ScanService
    library: DiscoveryLibrary | DemoLibrary
    knowledge: KnowledgeStore
    request_log: RequestLog


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def build_runtime_capabilities(runtime: Runtime) -> CapabilitiesReport:
    """Measure current capabilities from live service state, not config."""

    detector_manifest = None
    if runtime.scan.detector_loaded:
        try:
            from botanika.vision.detection import ModelManifest

            manifest = ModelManifest.from_file(runtime.settings.manifest_path)
            detector_manifest = {
                "model": manifest.model_name,
                "version": manifest.version,
                "license": manifest.license,
            }
        except Exception:
            detector_manifest = None

    storage_probe = runtime.library.probe()
    knowledge_probe = runtime.knowledge.probe()
    storage_ok = storage_probe == "ok"
    preview = runtime.scan.latest_preview()
    preview_ok = runtime.scan.is_running and preview is not None
    if preview_ok:
        preview_detail = f"Preview stream is available at sequence {preview.sequence}."
    elif not runtime.scan.is_running:
        preview_detail = "Scan service is not running."
    else:
        preview_detail = "Scan service has not published a preview frame."

    legacy = runtime.settings.legacy_demo_mode
    classifier_stub = True if legacy else runtime.scan.classifier_stub
    classifier_version = "stub-phase-4" if legacy else runtime.scan.classifier_version
    classifier_available = True if legacy else runtime.scan.classifier_available
    classifier_error = None if legacy else runtime.scan.classifier_error
    classifier_model = None if legacy else runtime.scan.classifier_model
    knowledge_available = False if legacy else knowledge_probe == "ok"
    knowledge_detail = (
        "Offline knowledge is not implemented until Phase 6."
        if legacy
        else (
            f"Offline catalog ready: {len(runtime.knowledge.catalog.species)} species; "
            f"region {runtime.knowledge.catalog.region}."
            if knowledge_probe == "ok"
            else knowledge_probe
        )
    )
    return build_capabilities(
        camera_error=runtime.scan.camera_error,
        camera_running=runtime.scan.camera_running,
        detector_error=runtime.scan.detector_error,
        detector_loaded=runtime.scan.detector_loaded,
        classifier_stub=classifier_stub,
        classifier_version=classifier_version,
        classifier_available=classifier_available,
        classifier_error=classifier_error,
        classifier_model=classifier_model,
        storage_ok=storage_ok,
        storage_detail=storage_probe if storage_probe != "ok" else knowledge_probe,
        library_error=None if storage_probe == "ok" else storage_probe,
        preview_ok=preview_ok,
        preview_detail=preview_detail,
        detector_manifest=detector_manifest,
        knowledge_available=knowledge_available,
        knowledge_detail=knowledge_detail,
        knowledge_model={
            "catalog_id": runtime.knowledge.catalog.catalog_id,
            "version": runtime.knowledge.catalog.version,
            "region": runtime.knowledge.catalog.region,
            "species_count": len(runtime.knowledge.catalog.species),
            "digest": runtime.knowledge.catalog.digest,
        },
    )
