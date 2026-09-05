#!/usr/bin/env python3
"""Run bounded smoke checks for every installed Botanika model/runtime.

This is intentionally a smoke/health check, not a field-accuracy claim.  It
never downloads a model, never persists a weed image, and never changes the
active model.  Pass a directory of downloaded/public or operator-owned images
with ``--images`` to exercise detector and embedding inference.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import resource
import sys
import time
from types import SimpleNamespace
from typing import Any

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SOURCE = PROJECT_ROOT / "backend" / "src"
if str(BACKEND_SOURCE) not in sys.path:
    sys.path.insert(0, str(BACKEND_SOURCE))

from botanika.core.settings import AppSettings  # noqa: E402
from botanika.knowledge.llm import LocalLLM  # noqa: E402
from botanika.vision.classification import (  # noqa: E402
    CampusFewShotClassifier,
    MobileNetV2Embedder,
)
from botanika.vision.detection import ModelManifest, YoloOnnxDetector  # noqa: E402
from botanika.vision.weeds import WeedService  # noqa: E402
from botanika.voice import AudioCoordinator  # noqa: E402


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def main(argv: list[str] | None = None) -> int:
    settings = AppSettings()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True, help="small directory of smoke-test images")
    parser.add_argument("--manifest", type=Path, default=settings.manifest_path)
    parser.add_argument("--embedding-model", type=Path, default=settings.embedding_model_path)
    parser.add_argument("--campus-artifact", type=Path, default=settings.campus_classifier_model_path)
    parser.add_argument("--catalog", type=Path, default=settings.species_catalog_path)
    parser.add_argument("--regional-catalog", type=Path, default=settings.regional_catalog_path)
    parser.add_argument("--llm-model", type=Path, default=settings.llm_model_path)
    parser.add_argument("--llama-cli", type=str, default=settings.llama_cli_path)
    parser.add_argument("--stt-models", type=Path, default=settings.stt_models_path)
    parser.add_argument("--stt-model-name", type=str, default=settings.stt_model_name)
    parser.add_argument("--tts-models", type=Path, default=settings.tts_models_path)
    parser.add_argument("--tts-model-name", type=str, default=settings.tts_model_name)
    parser.add_argument("--weed-manifest", type=Path, default=settings.weed_manifest_path)
    parser.add_argument("--skip-llm", action="store_true")
    parser.add_argument("--skip-voice", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)

    images_dir = args.images.expanduser().resolve()
    images = [path for path in sorted(images_dir.rglob("*")) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
    if not images:
        parser.error(f"no supported images found under {images_dir}")
    # Keep smoke checks bounded on a Pi and do not retain full frames.
    images = images[:8]
    result: dict[str, Any] = {
        "status": "ok",
        "host": {"platform": platform.platform(), "machine": platform.machine()},
        "images": [{"path": str(path), "sha256": _sha256(path)} for path in images],
        "models": {},
        "notes": [
            "Smoke checks prove load/inference wiring only; they do not establish field accuracy.",
            "Weed field testing remains the final operator checkpoint and is not claimed here.",
        ],
    }

    detector_result = _check_detector(args.manifest, images)
    result["models"]["generic_detector"] = detector_result
    if detector_result["status"] != "ok":
        result["status"] = "degraded"

    embedding_result = _check_embedding(args.embedding_model, images)
    result["models"]["plant_embedding"] = embedding_result
    if embedding_result["status"] != "ok":
        result["status"] = "degraded"

    campus_result = _check_campus(
        args.campus_artifact,
        args.embedding_model,
        args.catalog,
        args.regional_catalog,
        images,
    )
    result["models"]["campus_classifier"] = campus_result
    if campus_result["status"] == "error":
        result["status"] = "degraded"

    if args.skip_llm:
        result["models"]["qwen_llm"] = {"status": "skipped"}
    else:
        llm_result = _check_llm(args.llm_model, args.llama_cli)
        result["models"]["qwen_llm"] = llm_result
        if llm_result["status"] == "error":
            result["status"] = "degraded"

    if args.skip_voice:
        result["models"]["voice"] = {"status": "skipped"}
    else:
        voice_result = _check_voice(
            settings,
            stt_models_path=args.stt_models,
            stt_model_name=args.stt_model_name,
            tts_models_path=args.tts_models,
            tts_model_name=args.tts_model_name,
        )
        result["models"]["voice"] = voice_result
        # Audio hardware can be absent in a headless smoke environment; make
        # that explicit without marking the visual/model wiring broken.
        if voice_result["status"] == "error":
            result["status"] = "degraded"

    weed_result = _check_weed(settings, args.weed_manifest, images)
    result["models"]["weed_beta"] = weed_result
    if weed_result["status"] == "error":
        result["status"] = "degraded"

    result["rss_max_mb"] = round(float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) / 1024.0, 2)
    result["temperature_c"] = _temperature_c()
    serialized = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False)
    if args.output is not None:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized + "\n", encoding="utf-8")
    print(serialized)
    return 0 if result["status"] == "ok" else 1


def _check_detector(manifest_path: Path, images: list[Path]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        manifest = ModelManifest.from_file(manifest_path)
        # Match the production default so this smoke check exercises the same
        # post-processing path as the kiosk.  A zero threshold would produce
        # a misleading flood of low-confidence detections.
        detector = YoloOnnxDetector(manifest, confidence_threshold=0.25)
        detector.load()
        detections = []
        latencies = []
        for path in images:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            before = time.perf_counter()
            values = detector.detect(image)
            latencies.append((time.perf_counter() - before) * 1000.0)
            detections.append(
                {
                    "image": path.name,
                    "count": len(values),
                    "labels": [item.label for item in values[:10]],
                    "items": [
                        {"label": item.label, "confidence": round(float(item.confidence), 4)}
                        for item in values[:10]
                    ],
                }
            )
        if not detections:
            return {
                "status": "error",
                "detail": "detector could not decode any supplied image",
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
            }
        saturated = sum(1 for row in detections if int(row["count"]) >= detector.max_detections)
        plausibility = {
            "max_detections": detector.max_detections,
            "saturated_images": saturated,
            "saturation_guard": "pass" if saturated < len(detections) else "fail",
        }
        status = "ok" if saturated < len(detections) else "degraded"
        return {
            "status": status,
            "model": manifest.model_name,
            "version": manifest.version,
            "artifact_sha256": manifest.sha256,
            "images_run": len(detections),
            "detections": detections,
            "plausibility": plausibility,
            "latency_ms": _latency(latencies),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc), "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2)}


def _check_embedding(model_path: Path, images: list[Path]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        embedder = MobileNetV2Embedder(model_path)
        vectors = []
        latencies = []
        for path in images:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            before = time.perf_counter()
            vector = embedder.embed_views(image)
            latencies.append((time.perf_counter() - before) * 1000.0)
            vectors.append({"image": path.name, "dimensions": int(vector.size), "norm": round(float((vector * vector).sum() ** 0.5), 6)})
        return {
            "status": "ok",
            "model": embedder.metadata.to_dict(),
            "images_run": len(vectors),
            "vectors": vectors,
            "latency_ms": _latency(latencies),
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc), "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2)}


def _check_campus(
    artifact_path: Path,
    embedding_path: Path,
    catalog_path: Path,
    regional_catalog_path: Path,
    images: list[Path],
) -> dict[str, Any]:
    if not artifact_path.is_file():
        return {"status": "not-configured", "detail": f"No campus artifact at {artifact_path}; enroll campus photos first."}
    started = time.perf_counter()
    try:
        classifier = CampusFewShotClassifier(
            artifact_path,
            embedding_path,
            catalog_path,
            regional_catalog_path=regional_catalog_path,
        )
        rows = []
        for path in images:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            result = classifier.classify(image)
            rows.append({"image": path.name, "status": result.status.value, "confidence": result.confidence, "suggestions": [item.to_dict() for item in result.suggestions]})
        return {
            "status": "ok",
            "deployment_ready": classifier.deployment_ready,
            "deployment_blocker": classifier.deployment_blocker,
            "model": classifier.metadata.to_dict(),
            "images_run": len(rows),
            "results": rows,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }
    except Exception as exc:
        return {"status": "error", "detail": str(exc), "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2)}


def _check_llm(model_path: Path, cli_path: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        llm = LocalLLM(model_path, cli_path=cli_path, max_tokens=128, timeout_seconds=45)
        status = llm.status(load=True)
        result: dict[str, Any] = {"status": "ok" if status.available else "not-configured", "model": status.to_dict()}
        if status.available:
            evidence = (SimpleNamespace(chunk_id="model-smoke:chunk-1", content="Botanika smoke test plant fact."),)
            before = time.perf_counter()
            generated = llm.generate("Repeat the smoke test fact with citation.", evidence)
            result["grounded_generation_accepted"] = bool(generated)
            result["latency_ms"] = round((time.perf_counter() - before) * 1000.0, 2)
            if not generated:
                # The model did run, but the strict citation validator rejected
                # this sample.  Production intentionally falls back to the
                # already-grounded extractive answer in this case.
                result["application_fallback"] = "offline-extractive"
                result["detail"] = (
                    "Model load/inference passed; the sample output was rejected by the "
                    "citation gate and production uses the grounded extractive fallback."
                )
        result["elapsed_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        return result
    except Exception as exc:
        return {"status": "error", "detail": str(exc), "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2)}


def _check_voice(
    settings: AppSettings,
    *,
    stt_models_path: Path | None = None,
    stt_model_name: str | None = None,
    tts_models_path: Path | None = None,
    tts_model_name: str | None = None,
) -> dict[str, Any]:
    try:
        voice_settings = AppSettings(
            stt_models_path=stt_models_path or settings.stt_models_path,
            stt_model_name=stt_model_name if stt_model_name is not None else settings.stt_model_name,
            tts_models_path=tts_models_path or settings.tts_models_path,
            tts_model_name=tts_model_name if tts_model_name is not None else settings.tts_model_name,
        )
        voice = AudioCoordinator(voice_settings)
        status = voice.status(load_models=True)
        return {"status": "ok" if status.stt_available and status.tts_available else "not-configured", "model": status.to_dict()}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_weed(settings: AppSettings, manifest_path: Path, images: list[Path]) -> dict[str, Any]:
    try:
        local_settings = settings if manifest_path == settings.weed_manifest_path else AppSettings(weed_manifest_path=manifest_path)
        service = WeedService(local_settings)
        status = service.status()
        if not status.available:
            return {"status": "not-configured", "detail": status.detail, "model": status.to_dict()}
        rows = []
        for path in images:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                continue
            value = service.detect_image(image)
            rows.append({"image": path.name, "status": value.get("status"), "detections": len(value.get("detections", [])), "image_persisted": value.get("image_persisted")})
        return {"status": "ok", "model": status.to_dict(), "images_run": len(rows), "results": rows, "field_acceptance": "not claimed"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc), "field_acceptance": "not claimed"}


def _latency(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"samples": 0, "p50": None, "p95": None, "max": None}
    ordered = sorted(values)
    return {
        "samples": len(ordered),
        "p50": round(ordered[len(ordered) // 2], 2),
        "p95": round(ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))], 2),
        "max": round(max(ordered), 2),
    }


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _temperature_c() -> float | None:
    for path in sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp")):
        try:
            return round(float(path.read_text().strip()) / 1000.0, 2)
        except (OSError, ValueError):
            continue
    return None


if __name__ == "__main__":
    raise SystemExit(main())
