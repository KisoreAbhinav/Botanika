"""Scan screen routes: state, preview stream, event channel, and commands."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

import cv2
import numpy as np
from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import StreamingResponse

from botanika.api.runtime import Runtime, get_runtime
from botanika.api.schemas import FallbackCaptureRequest, OkResponse, SelectBoxRequest
from botanika.core.errors import ValidationError

router = APIRouter(prefix="/scan", tags=["scan"])
MJPG_BOUNDARY = b"--frame"
MJPG_HEADER = b"Content-Type: image/jpeg\r\nContent-Length: "


@router.get("/state")
async def scan_state(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    snapshot = runtime.scan.latest_snapshot()
    if snapshot is None:
        return {
            "sequence": 0,
            "state": "starting",
            "hint": "Scan service is starting.",
            "detections": [],
            "processing": False,
            "camera_available": False,
            "error": None,
        }
    return snapshot.to_dict()


@router.post("/manual-capture", response_model=OkResponse)
async def manual_capture(request: Request) -> OkResponse:
    get_runtime(request).scan.request_manual_capture()
    return OkResponse(detail="manual capture requested")


@router.post("/select", response_model=OkResponse)
async def select_box(request: Request, body: SelectBoxRequest) -> OkResponse:
    accepted = get_runtime(request).scan.request_select_box(body.index)
    if not accepted:
        raise ValidationError("the selected box index is not available")
    return OkResponse(detail=f"selected detection box {body.index}")


@router.post("/retake", response_model=OkResponse)
async def retake(request: Request) -> OkResponse:
    get_runtime(request).scan.request_retake()
    return OkResponse(detail="scan reset to detection")


@router.post("/cancel", response_model=OkResponse)
async def cancel(request: Request) -> OkResponse:
    get_runtime(request).scan.request_cancel()
    return OkResponse(detail="scan cancelled")


@router.post("/fallback", response_model=OkResponse)
async def fallback_upload(request: Request, file: UploadFile = File(...)) -> OkResponse:
    runtime = get_runtime(request)
    payload = await file.read(runtime.settings.max_fallback_upload_bytes + 1)
    if not payload:
        raise ValidationError("the uploaded local image is empty")
    if len(payload) > runtime.settings.max_fallback_upload_bytes:
        raise ValidationError("the uploaded local image exceeds the 12 MiB limit")
    image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValidationError("the uploaded file could not be decoded as an image")
    try:
        runtime.scan.set_fallback_image(image, file.filename or "local image")
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return OkResponse(detail="local image selected for analysis")


@router.post("/fallback/capture", response_model=OkResponse)
async def fallback_capture(request: Request, body: FallbackCaptureRequest) -> OkResponse:
    accepted = get_runtime(request).scan.request_fallback_capture(body.index)
    if not accepted:
        raise ValidationError("no eligible target at that index in the local image")
    return OkResponse(detail="local-image capture requested")


@router.post("/fallback/clear", response_model=OkResponse)
async def fallback_clear(request: Request) -> OkResponse:
    get_runtime(request).scan.clear_fallback()
    return OkResponse(detail="local image cleared")


@router.get("/preview.mjpg", include_in_schema=False)
async def preview_stream(request: Request) -> StreamingResponse:
    """Backend-owned MJPEG stream of the latest letterboxed preview frame."""

    runtime = get_runtime(request)
    return StreamingResponse(
        _mjpg_generator(runtime),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _mjpg_generator(runtime: Runtime) -> AsyncGenerator[bytes, None]:
    last_sequence = -1
    while True:
        preview = runtime.scan.latest_preview()
        if preview is None or preview.sequence == last_sequence:
            await asyncio.sleep(0.04)
            continue
        last_sequence = preview.sequence
        length = str(len(preview.jpeg_bytes)).encode("ascii")
        yield (
            MJPG_BOUNDARY
            + b"\r\n"
            + MJPG_HEADER
            + length
            + b"\r\n\r\n"
            + preview.jpeg_bytes
            + b"\r\n"
        )
        await asyncio.sleep(0)


@router.get("/events", include_in_schema=False)
async def event_stream(request: Request) -> StreamingResponse:
    """Server-sent snapshot events for boxes, quality, and scan state."""

    runtime = get_runtime(request)
    return StreamingResponse(
        _sse_generator(runtime),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_generator(runtime: Runtime) -> AsyncGenerator[str, None]:
    yield ": connected\n\n"
    last_id = runtime.scan.events.last_sequence
    snapshot = runtime.scan.events.latest()
    if snapshot is not None:
        last_id = snapshot.sequence
        yield _sse_event(snapshot.sequence, snapshot.to_dict())
    while True:
        pending = runtime.scan.events.after(last_id)
        if not pending:
            await asyncio.sleep(0.05)
            continue
        for item in pending:
            last_id = item.sequence
            yield _sse_event(item.sequence, item.to_dict())
        await asyncio.sleep(0)


def _sse_event(sequence: int, payload: dict[str, Any]) -> str:
    return (
        f"id: {sequence}\n"
        f"event: snapshot\n"
        f"data: {json.dumps(payload)}\n\n"
    )
