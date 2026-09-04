"""Explicitly bounded independent weed-beta routes."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile

from botanika.api.auth import require_local_operator, require_local_or_controller
from botanika.api.concurrency import run_blocking
from botanika.api.runtime import get_runtime
from botanika.core.errors import CapabilityUnavailableError, ValidationError
from botanika.storage.weeds import NO_POSITION_MESSAGE


router = APIRouter(prefix="/weeds", tags=["weeds"])


@router.get("/status")
async def weed_status(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.weeds is None:
        return {
            "available": False,
            "state": "unavailable",
            "detail": "Independent weed detector is not initialized.",
            "image_persistence": "disabled",
        }
    return runtime.weeds.status().to_dict()


@router.post("/camera")
@router.post("/detect")
async def detect_camera(request: Request) -> dict[str, Any]:
    """Analyze exactly one in-memory Pi frame; the shared scan owner keeps camera access."""

    require_local_operator(request)
    runtime = get_runtime(request)
    if runtime.weeds is None:
        raise CapabilityUnavailableError("independent weed detector is unavailable")
    frame = runtime.scan.latest_frame()
    if frame is None:
        return {
            "status": "unavailable",
            "detail": "The Pi camera has not published a frame.",
            "detections": [],
            "position_message": NO_POSITION_MESSAGE,
            "image_persisted": False,
        }
    try:
        return await run_blocking(runtime.weeds.detect_image, frame, include_frame=True)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc


@router.post("/controller/frame")
@router.post("/frame")
async def detect_controller_frame(
    request: Request,
    file: UploadFile = File(...),
    position_json: str | None = Form(default=None),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
    accuracy_m: float | None = Form(default=None),
    position_source: str | None = Form(default=None),
    position_timestamp: float | None = Form(default=None),
) -> dict[str, Any]:
    """Analyze one still from the paired browser, with optional accurate position."""

    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.weeds is None:
        raise CapabilityUnavailableError("independent weed detector is unavailable")
    payload = await file.read(runtime.settings.weed_max_upload_bytes + 1)
    if len(payload) > runtime.settings.weed_max_upload_bytes:
        raise ValidationError("weed image exceeds the configured upload limit")
    try:
        position = _position_from_form(
            position_json,
            latitude=latitude,
            longitude=longitude,
            accuracy_m=accuracy_m,
            source=position_source,
            timestamp=position_timestamp,
        )
        return await run_blocking(runtime.weeds.detect_bytes, payload, position=position)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValidationError(str(exc)) from exc


def _position_from_form(
    encoded: str | None,
    *,
    latitude: float | None,
    longitude: float | None,
    accuracy_m: float | None,
    source: str | None,
    timestamp: float | None,
) -> dict[str, Any] | None:
    if encoded is not None and encoded.strip():
        value = json.loads(encoded)
        if not isinstance(value, dict):
            raise ValueError("position_json must be an object")
        return value
    supplied = (latitude, longitude, accuracy_m, source, timestamp)
    if all(item is None for item in supplied):
        return None
    if latitude is None or longitude is None or accuracy_m is None or not source:
        raise ValueError("position requires latitude, longitude, accuracy_m, and position_source")
    value: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "accuracy_m": accuracy_m,
        "source": source,
    }
    if timestamp is not None:
        value["timestamp"] = timestamp
    return value


__all__ = ["router"]
