#!/usr/bin/env python3
"""Verify deterministic Phase 9 contracts without hardware or network access.

This verifier checks source/manifests, indexed knowledge, bounded voice state,
library progress derivation, and independent weed-beta persistence. It does not
claim that a microphone, speaker, display, camera, model artifact, or Pi
operator journey has passed; those remain measured deployment gates.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
from dataclasses import dataclass
import io
import json
from pathlib import Path
import sys
import tempfile
import wave
import re

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import AppSettings
from botanika.api.concurrency import run_blocking
from botanika.knowledge import KnowledgeStore
from botanika.knowledge.llm import validate_grounded_output
from botanika.storage import DiscoveryLibrary, NO_POSITION_MESSAGE, WeedObservationStore
from botanika.vision.detection import BoundingBox, Detection
from botanika.vision.weeds import WeedService
from botanika.voice import endpoint_reached, validate_wav


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


FILES = (
    "config/knowledge/source-license-manifest.json",
    "config/llm/phase9-llama.example.json",
    "config/weed/phase9-beta.json",
    "backend/src/botanika/knowledge/embeddings.py",
    "backend/src/botanika/knowledge/llm.py",
    "backend/src/botanika/voice/coordinator.py",
    "backend/src/botanika/api/routes/voice.py",
    "backend/src/botanika/api/routes/weeds.py",
    "backend/src/botanika/storage/weeds.py",
    "backend/src/botanika/vision/weeds/service.py",
    "frontend/src/features/ask/AskPage.jsx",
    "frontend/src/features/weeds/WeedsPage.jsx",
    "tools/ingest_knowledge.py",
    "tools/benchmark_local_llm.py",
    "tools/launch_kiosk.py",
    "deploy/systemd/botanika-kiosk.service",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="fail if a deterministic check fails")
    args = parser.parse_args(argv)
    checks = static_checks()
    checks.extend(deterministic_checks())
    payload = {
        "phase": 9,
        "checks": [check.to_dict() for check in checks],
        "physical_gates": {
            "status": "not_claimed",
            "detail": "Camera, display, microphone, speaker, model benchmark, cold boot, offline journey, and soak require a Pi operator run.",
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Botanika Phase 9 deterministic verification")
        for check in checks:
            print(f"[{'PASS' if check.passed else 'FAIL'}] {check.name}: {check.detail}")
        print("[GATE] physical: not claimed; run the Pi/operator checklist before release")
    return 1 if args.strict and any(not check.passed for check in checks) else 0


def static_checks() -> list[Check]:
    checks: list[Check] = []
    for relative in FILES:
        path = PROJECT_ROOT / relative
        checks.append(Check(f"file:{relative}", path.is_file(), "present" if path.is_file() else "missing"))
    try:
        source_manifest = json.loads((PROJECT_ROOT / "config/knowledge/source-license-manifest.json").read_text(encoding="utf-8"))
        llm_manifest = json.loads((PROJECT_ROOT / "config/llm/phase9-llama.example.json").read_text(encoding="utf-8"))
        weed_manifest = json.loads((PROJECT_ROOT / "config/weed/phase9-beta.json").read_text(encoding="utf-8"))
        provenance_ok = all(
            item.get("source_id") and item.get("url") and item.get("license")
            for item in source_manifest.get("sources", [])
        ) and bool(source_manifest.get("catalog_sha256"))
        checks.append(Check("source-license-provenance", provenance_ok, "source IDs, URLs, licenses, and catalog checksum are declared"))
        llm_sha = str(llm_manifest.get("sha256", ""))
        sha_is_real = bool(re.fullmatch(r"[0-9a-fA-F]{64}", llm_sha)) and llm_sha != "0" * 64
        sha_is_explicit_placeholder = llm_sha.startswith("REPLACE_WITH_")
        checks.append(Check("llm-release-contract", llm_manifest.get("runtime") == "llama.cpp" and (sha_is_real or sha_is_explicit_placeholder) and llm_manifest.get("download_policy", "").startswith("manual"), "quantized local runtime settings and a manual verification slot are declared"))
        model_path = PROJECT_ROOT / "models" / "llm" / "botanika.gguf"
        checksum_state_ok = not model_path.is_file() or sha_is_real
        checks.append(Check("llm-checksum-state", checksum_state_ok, "an installed GGUF must have a real manifest checksum; the absent example asset remains explicitly unverified"))
        checks.append(Check("weed-safety-boundary", bool(weed_manifest.get("crop_context")) and bool(weed_manifest.get("region")) and not any(token in json.dumps(weed_manifest).lower() for token in ("drone", "chemical")), "weed manifest names crop/region/classes without operational chemical or drone behavior"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        checks.append(Check("manifest-json", False, str(exc)))
    chat_source = (PROJECT_ROOT / "frontend/src/features/ask/AskPage.jsx").read_text(encoding="utf-8")
    weed_source = (PROJECT_ROOT / "frontend/src/features/weeds/WeedsPage.jsx").read_text(encoding="utf-8")
    weed_backend_source = (PROJECT_ROOT / "backend/src/botanika/vision/weeds/service.py").read_text(encoding="utf-8")
    voice_source = (PROJECT_ROOT / "backend/src/botanika/voice/coordinator.py").read_text(encoding="utf-8")
    checks.append(Check("chat-abstention-citations", "Evidence insufficient" in chat_source and "citations" in chat_source and "typed_chat_remains_available" in voice_source, "typed transcript, citations, explicit abstention, and typed fallback are represented"))
    checks.append(Check("local-voice-navigation", "navigationDestination" in chat_source and "onNavigate" in chat_source, "spoken navigation can move between local screens without adding a remote dependency"))
    checks.append(Check("voice-owner-bounds", "_owner_lock" in voice_source and "voice_max_turn_seconds" in voice_source and "voice_short_silence_seconds" in voice_source and "interrupt" in voice_source, "one audio owner, bounded turn length, endpointing, cached models, and interruption are present"))
    route_voice_source = (PROJECT_ROOT / "backend/src/botanika/api/routes/voice.py").read_text(encoding="utf-8")
    route_species_source = (PROJECT_ROOT / "backend/src/botanika/api/routes/species.py").read_text(encoding="utf-8")
    route_weeds_source = (PROJECT_ROOT / "backend/src/botanika/api/routes/weeds.py").read_text(encoding="utf-8")
    checks.append(Check("blocking-work-offloaded", all(token in source for source, token in ((route_voice_source, "await run_blocking(runtime.voice.listen_once)"), (route_voice_source, "await run_blocking(runtime.voice.transcribe_wav"), (route_species_source, "await run_blocking("), (route_weeds_source, "run_blocking(runtime.weeds.detect"))), "blocking audio, LLM, and detector work is kept off the FastAPI event loop"))
    checks.append(Check("weed-ui-boxes", "DetectionBox" in weed_source and "image_persisted" in weed_backend_source and "EXACT_POSITION_MESSAGE" in weed_source and "capture=\"environment\"" in weed_source and "frame_data_url" in weed_source, "supported multi-box/confidence display, native still capture, exact analyzed SOLO frame, and no-image persistence boundary are present"))
    checks.append(Check("weed-contained-geometry", "containedImageRect" in weed_source and "weed-frame-layer" in weed_source, "weed boxes share the contained analyzed-frame layer at changing aspect ratios"))
    service_unit = (PROJECT_ROOT / "deploy/systemd/botanika-backend.service").read_text(encoding="utf-8")
    unit_limit_start = service_unit.find("StartLimitIntervalSec=")
    service_start = service_unit.find("[Service]")
    env_source = (PROJECT_ROOT / "config/environments/phase7-network.env.example").read_text(encoding="utf-8")
    tmpfiles_source = (PROJECT_ROOT / "deploy/systemd/botanika-tmpfiles.conf").read_text(encoding="utf-8")
    runtime_dirs_ok = all(item in env_source for item in ("BOTANIKA_DATABASE_PATH=/var/lib/botanika/", "BOTANIKA_TEMP_CROPS_DIR=/var/lib/botanika/", "BOTANIKA_DISCOVERIES_DIR=/var/lib/botanika/", "BOTANIKA_BACKUP_DIR=/var/lib/botanika/")) and 0 <= unit_limit_start < service_start and "/var/lib/botanika" in tmpfiles_source
    checks.append(Check("production-runtime-directories", runtime_dirs_ok, "production state paths are wired and restart limits live in the systemd Unit section"))
    kiosk_source = (PROJECT_ROOT / "tools/launch_kiosk.py").read_text(encoding="utf-8")
    checks.append(Check("readiness-kiosk", "health/ready" in kiosk_source and "--kiosk" in kiosk_source and "800,480" in kiosk_source, "Chromium launch waits for local readiness and fixes the Pi canvas size"))
    return checks


def deterministic_checks() -> list[Check]:
    checks: list[Check] = []

    async def verify_blocking_bridge() -> bool:
        def add(left: int, *, right: int) -> int:
            return left + right

        def fail_in_worker() -> None:
            raise RuntimeError("phase9 verifier worker failure")

        value = await asyncio.wait_for(run_blocking(add, 2, right=3), timeout=1.0)
        try:
            await asyncio.wait_for(run_blocking(fail_in_worker), timeout=1.0)
        except RuntimeError as exc:
            return value == 5 and str(exc) == "phase9 verifier worker failure"
        return False

    try:
        bridge_ok = asyncio.run(verify_blocking_bridge())
        bridge_detail = "bounded executor supports kwargs and propagates worker exceptions"
    except Exception as exc:  # pragma: no cover - defensive CLI verification boundary
        bridge_ok = False
        bridge_detail = f"bounded executor check failed: {exc}"
    checks.append(Check("blocking-bridge-runtime", bridge_ok, bridge_detail))

    with tempfile.TemporaryDirectory(prefix="botanika-phase9-") as directory:
        root = Path(directory)
        store = KnowledgeStore(root / "knowledge.sqlite", PROJECT_ROOT / "config/catalog/india-starter-species.json")
        try:
            status = store.ingestion_status()
            known = store.answer("Where is the banyan native?")
            unknown = store.answer("What is the moon made of?")
            checks.append(Check("knowledge-index", status.get("chunk_count") == "14" and status.get("embedding_dimensions") == "256", "FTS5 seed and compact embedding index contain the reviewed chunk set"))
            checks.append(Check("grounded-abstention", not known.abstained and bool(known.citations) and unknown.abstained, "known question is cited and unrelated question abstains"))

            library = DiscoveryLibrary(root / "library.sqlite", root / "media")
            try:
                progress = library.progress(store.catalog.species)
                checks.append(Check("reproducible-progress", progress["supported_species"] == 7 and progress["discovered_species"] == 0 and progress["coverage_percent"] == 0.0, "progress is derived from active records and starts at zero"))
            finally:
                library.close()
        finally:
            store.close()

        audio = io.BytesIO()
        with wave.open(audio, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16000)
            output.writeframes(b"\x00\x00" * 1600)
        samples, rate = validate_wav(audio.getvalue(), max_bytes=100000, max_seconds=2)
        checks.append(Check("voice-validation", rate == 16000 and len(samples) == 1600 and endpoint_reached(speech_detected=True, silence_seconds=1.0, short_silence_seconds=1.0, long_silence_seconds=5.0) == "end", "audio format and short-silence endpoint are bounded"))

        database_path = root / "weeds.sqlite"
        settings = AppSettings(weed_manifest_path=PROJECT_ROOT / "config/weed/phase9-beta.json", database_path=database_path, discoveries_dir=root / "discoveries")
        observations = WeedObservationStore(database_path=database_path)

        class FakeDetector:
            def detect(self, _image):
                return [Detection(0, "parthenium", 0.81, BoundingBox(10, 20, 100, 120))]

        weeds = WeedService(settings, detector=FakeDetector(), observation_store=observations)
        import numpy as np

        image = np.zeros((160, 240, 3), dtype=np.uint8)
        no_position = weeds.detect_image(image)
        missing_source = weeds.detect_image(image, position={"latitude": 18.52, "longitude": 73.85, "accuracy_m": 10})
        inaccurate = weeds.detect_image(image, position={"latitude": 18.52, "longitude": 73.85, "accuracy_m": 101, "source": "verifier", "timestamp": 100})
        with_position = weeds.detect_image(
            image,
            position={"latitude": 18.52, "longitude": 73.85, "accuracy_m": 10, "source": "verifier", "timestamp": 100},
        )
        class EmptyDetector:
            def detect(self, _image):
                return []

        empty_weeds = WeedService(settings, detector=EmptyDetector(), observation_store=observations)
        empty = empty_weeds.detect_image(image, position={"latitude": 18.52, "longitude": 73.85, "accuracy_m": 10, "source": "verifier", "timestamp": 100})
        checks.append(Check("weed-position-boundary", all(item["position_message"] == NO_POSITION_MESSAGE for item in (no_position, missing_source, inaccurate)) and observations.count() == 1 and observations.run_count() == 1 and empty["run_id"] is None and with_position["image_persisted"] is False, "missing, incomplete, inaccurate, and zero-detection runs leave no persistence while accurate detections create one coordinate-only run"))
        checks.append(Check("weed-transient-frame", with_position.get("frame_data_url") is None and weeds.detect_image(image, include_frame=True).get("frame_data_url", "").startswith("data:image/jpeg;base64,"), "an analyzed frame is available only as an in-memory response when explicitly requested"))
        checks.append(Check("llm-statement-grounding", validate_grounded_output("Banyan is native [chunk-a]. It is a tree.", {"chunk-a"}) is False and validate_grounded_output("Banyan is native [chunk-a]. It is a tree [chunk-a].", {"chunk-a"}), "uncited factual statements are rejected while individually cited statements are accepted"))
        observations.close()
    return checks


if __name__ == "__main__":
    raise SystemExit(main())
