"""Capability reporting based on measured runtime state, never configuration intent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class CapabilityState:
    """One labelled capability and its honest availability description."""

    name: str
    available: bool
    detail: str
    model: dict[str, object] | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "available": self.available,
            "detail": self.detail,
        }
        if self.model is not None:
            value["model"] = self.model
        return value


@dataclass(frozen=True, slots=True)
class CapabilitiesReport:
    """Full capability snapshot rendered by ``/capabilities`` and ``/ready``."""

    camera: CapabilityState
    detector: CapabilityState
    classifier: CapabilityState
    knowledge: CapabilityState
    storage: CapabilityState
    library: CapabilityState
    preview: CapabilityState
    # Phase 5/6 callers construct this report directly, so the network field
    # is optional for backwards compatibility. AP mode marks it required at
    # runtime; SOLO readiness does not depend on an optional private link.
    network: CapabilityState = field(
        default_factory=lambda: CapabilityState(
            "network",
            False,
            "Private Wi-Fi access point is not configured.",
        )
    )
    network_required: bool = False
    mode: CapabilityState = field(
        default_factory=lambda: CapabilityState(
            "mode",
            True,
            "SOLO/NETWORKED handoff is available through the software fallback.",
        )
    )
    llm: CapabilityState = field(
        default_factory=lambda: CapabilityState(
            "llm",
            False,
            "Optional local generation model is unavailable; extractive answers remain available.",
        )
    )
    voice: CapabilityState = field(
        default_factory=lambda: CapabilityState(
            "voice",
            False,
            "Pi voice input/output is unavailable; typed chat remains available.",
        )
    )
    weeds: CapabilityState = field(
        default_factory=lambda: CapabilityState(
            "weeds",
            False,
            "Independent weed-beta detector is unavailable.",
        )
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "camera": self.camera.to_dict(),
            "detector": self.detector.to_dict(),
            "classifier": self.classifier.to_dict(),
            "knowledge": self.knowledge.to_dict(),
            "storage": self.storage.to_dict(),
            "library": self.library.to_dict(),
            "preview": self.preview.to_dict(),
            "network": self.network.to_dict(),
            "mode": self.mode.to_dict(),
            "llm": self.llm.to_dict(),
            "voice": self.voice.to_dict(),
            "weeds": self.weeds.to_dict(),
        }

    @property
    def ready(self) -> bool:
        """The application is ready when its core data and serving paths work.

        Camera/detector may be degraded alone: the kiosk must stay usable with
        the local image fallback, but storage and library must be sound.
        """

        core_ready = all(
            (
                self.classifier.available,
                self.knowledge.available,
                self.storage.available,
                self.library.available,
                self.preview.available,
            )
        )
        return core_ready and (not self.network_required or self.network.available)


def build_capabilities(
    *,
    camera_error: str | None,
    camera_running: bool,
    detector_error: str | None,
    detector_loaded: bool,
    classifier_stub: bool,
    classifier_version: str,
    storage_ok: bool,
    storage_detail: str,
    library_error: str | None,
    preview_ok: bool,
    preview_detail: str,
    detector_manifest: dict[str, str] | None = None,
    classifier_available: bool | None = None,
    classifier_error: str | None = None,
    classifier_model: dict[str, object] | None = None,
    knowledge_available: bool = False,
    knowledge_detail: str = "Offline knowledge is unavailable.",
    knowledge_model: dict[str, object] | None = None,
    network_available: bool = False,
    network_detail: str = "Private Wi-Fi access point is unavailable.",
    network_model: dict[str, object] | None = None,
    network_required: bool = False,
    mode_available: bool = True,
    mode_detail: str = "SOLO/NETWORKED handoff is available.",
    mode_model: dict[str, object] | None = None,
    llm_available: bool = False,
    llm_detail: str = "Optional local generation model is unavailable; extractive answers remain available.",
    llm_model: dict[str, object] | None = None,
    voice_available: bool = False,
    voice_detail: str = "Pi voice input/output is unavailable; typed chat remains available.",
    voice_model: dict[str, object] | None = None,
    weeds_available: bool = False,
    weeds_detail: str = "Independent weed-beta detector is unavailable.",
    weeds_model: dict[str, object] | None = None,
) -> CapabilitiesReport:
    """Assemble an honest capability report from measured runtime values."""

    if camera_running and camera_error is None:
        camera = CapabilityState("camera", True, "Pi Camera is owned and streaming.")
    else:
        camera = CapabilityState(
            "camera",
            False,
            camera_error or "Pi Camera is not currently running.",
        )

    if detector_loaded and detector_error is None:
        detector_detail = "Generic YOLO detector is loaded."
        detector_model = detector_manifest
    else:
        detector_detail = detector_error or "Detector is not loaded."
        detector_model = None
    detector = CapabilityState("detector", detector_loaded and detector_error is None, detector_detail, detector_model)

    if classifier_available is None:
        classifier_available = not classifier_stub
    if classifier_available and not classifier_stub:
        classifier_detail = "Validated compact catalog classifier is loaded; unknown views are rejected."
    elif classifier_available and classifier_stub:
        classifier_detail = "Phase 4 deterministic stub is available only for development."
    else:
        classifier_detail = classifier_error or "Species classifier is unavailable."
    classifier = CapabilityState(
        "classifier",
        bool(classifier_available),
        classifier_detail,
        classifier_model
        or {"version": classifier_version, "is_stub": str(bool(classifier_stub)).lower()},
    )

    knowledge = CapabilityState(
        "knowledge",
        knowledge_available,
        knowledge_detail,
        knowledge_model,
    )

    storage = CapabilityState("storage", storage_ok, storage_detail)
    library = CapabilityState(
        "library",
        library_error is None,
        library_error or "Species-grouped discovery library is writable.",
    )
    preview = CapabilityState("preview", preview_ok, preview_detail)
    network = CapabilityState(
        "network",
        network_available,
        network_detail,
        network_model,
    )
    mode = CapabilityState("mode", mode_available, mode_detail, mode_model)
    llm = CapabilityState("llm", llm_available, llm_detail, llm_model)
    voice = CapabilityState("voice", voice_available, voice_detail, voice_model)
    weeds = CapabilityState("weeds", weeds_available, weeds_detail, weeds_model)

    return CapabilitiesReport(
        camera=camera,
        detector=detector,
        classifier=classifier,
        knowledge=knowledge,
        storage=storage,
        library=library,
        preview=preview,
        network=network,
        mode=mode,
        network_required=network_required,
        llm=llm,
        voice=voice,
        weeds=weeds,
    )


def empty_capabilities(message: str = "Application is starting.") -> CapabilitiesReport:
    """Report every capability unavailable before the runtime initializes."""

    unavailable = CapabilityState("", False, message)
    return CapabilitiesReport(
        camera=unavailable,
        detector=unavailable,
        classifier=unavailable,
        knowledge=unavailable,
        storage=unavailable,
        library=unavailable,
        preview=unavailable,
        network=unavailable,
        mode=CapabilityState("mode", False, message),
        llm=unavailable,
        voice=unavailable,
        weeds=unavailable,
    )
