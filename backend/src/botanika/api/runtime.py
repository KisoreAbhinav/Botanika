"""Runtime container shared by all API routes."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from botanika.core.capabilities import CapabilitiesReport, build_capabilities
from botanika.core.settings import AppSettings
from botanika.knowledge import KnowledgeStore
from botanika.knowledge.llm import LocalLLM
from botanika.hardware.gpio import ModeGPIOAdapter
from botanika.mode import ModeService
from botanika.network import NetworkService
from botanika.observability import RequestLog
from botanika.storage import DemoLibrary, DiscoveryLibrary, WeedObservationStore
from botanika.vision.services.scan import ScanService
from botanika.vision.weeds import WeedService
from botanika.voice import AudioCoordinator

APP_VERSION = "0.9.0"


@dataclass(slots=True)
class Runtime:
    """Long-lived application services owned by the FastAPI lifespan."""

    settings: AppSettings
    scan: ScanService
    library: DiscoveryLibrary | DemoLibrary
    knowledge: KnowledgeStore
    request_log: RequestLog
    network: NetworkService | None = None
    mode: ModeService | None = None
    gpio: ModeGPIOAdapter | None = None
    llm: LocalLLM | None = None
    voice: AudioCoordinator | None = None
    weeds: WeedService | None = None
    weed_observations: WeedObservationStore | None = None

    def network_status(self) -> dict[str, object]:
        service = self.network or NetworkService(self.settings)
        return service.to_dict()

    def mode_status(self) -> dict[str, object]:
        service = self.mode or ModeService(self.settings)
        network = self.network_status()
        scan = self.scan.latest_snapshot()
        scan_value = _scan_summary(scan)
        return service.status(network=network, scan=scan_value)


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

    network_service = runtime.network or NetworkService(runtime.settings)
    network_status = network_service.status()
    network_model = network_service.to_dict()
    tunnel_model = network_model.get("tunnel")
    tunnel_ready = isinstance(tunnel_model, dict) and tunnel_model.get("state") == "ready"
    network_available = network_status.available or tunnel_ready
    # Use the aggregate transport detail so an available private AP is not
    # reported as unhealthy merely because the optional tunnel is idle.
    network_detail = str(network_model.get("detail") or network_status.detail)
    mode_service = runtime.mode or ModeService(runtime.settings)
    mode_status = mode_service.status(
        network=network_model,
        scan=_scan_summary(runtime.scan.latest_snapshot()),
    )

    llm_service = getattr(runtime, "llm", None)
    voice_service = getattr(runtime, "voice", None)
    weeds_service = getattr(runtime, "weeds", None)
    llm = llm_service.status() if llm_service is not None else None
    voice = voice_service.status() if voice_service is not None else None
    weeds = weeds_service.status() if weeds_service is not None else None

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
        network_available=network_available,
        network_detail=network_detail,
        network_model=network_model,
        network_required=runtime.settings.network_enabled,
        mode_available=True,
        mode_detail=f"Application mode is {mode_status['mode']}; one controller maximum.",
        mode_model={
            "mode": mode_status["mode"],
            "controller_count": mode_status["controller_count"],
            "gpio_available": bool(runtime.gpio and runtime.gpio.available),
        },
        llm_available=bool(llm and llm.available),
        llm_detail=(llm.detail if llm is not None else "Local generation adapter is not initialized."),
        llm_model=(llm.to_dict() if llm is not None else None),
        voice_available=bool(voice and voice.available),
        voice_detail=(voice.detail if voice is not None else "Pi voice coordinator is not initialized."),
        voice_model=(voice.to_dict() if voice is not None else None),
        weeds_available=bool(weeds and weeds.available),
        weeds_detail=(weeds.detail if weeds is not None else "Independent weed detector is not initialized."),
        weeds_model=(weeds.to_dict() if weeds is not None else None),
    )


def _scan_summary(snapshot: object | None) -> dict[str, object]:
    if snapshot is None or not hasattr(snapshot, "to_dict"):
        return {}
    try:
        value = snapshot.to_dict()
    except Exception:
        return {}
    if not isinstance(value, dict):
        return {}
    result = value.get("classification")
    return {
        "state": value.get("state"),
        "hint": value.get("hint"),
        "processing": value.get("processing", False),
        "result": (
            result.get("result")
            if isinstance(result, dict)
            else None
        ),
        "timestamp": value.get("timestamp"),
    }
