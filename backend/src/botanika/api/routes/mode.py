"""Phase 8 mode, pairing, controller, and crop-only upload routes."""

from __future__ import annotations

import hashlib
from typing import Any
import uuid

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, Request, Response, UploadFile

from botanika.api.auth import (
    CONTROLLER_COOKIE,
    controller_token,
    mode_status_for_request,
    require_controller,
    require_local_operator,
)
from botanika.api.runtime import get_runtime
from botanika.api.schemas import DeviceRequest, ModeSetRequest, PairingRequest
from botanika.core.errors import ControllerAuthorizationError, ValidationError
from botanika.mode import (
    Mode,
    ModeError,
    PairingAuthenticationError,
    PairingError,
)


router = APIRouter(prefix="/mode", tags=["mode"])


@router.get("", response_model=dict[str, Any])
@router.get("/status", response_model=dict[str, Any])
async def mode_status(request: Request) -> dict[str, Any]:
    return mode_status_for_request(get_runtime(request).mode_status(), request)


@router.post("/toggle", response_model=dict[str, Any])
async def toggle_mode(request: Request) -> dict[str, Any]:
    require_local_operator(request)
    runtime = get_runtime(request)
    try:
        runtime.mode.toggle()
    except ModeError as exc:
        raise ValidationError(str(exc)) from exc
    return mode_status_for_request(runtime.mode_status(), request)


@router.post("/networked", response_model=dict[str, Any])
@router.post("/enter-networked", response_model=dict[str, Any])
async def enter_networked(request: Request) -> dict[str, Any]:
    require_local_operator(request)
    runtime = get_runtime(request)
    try:
        runtime.mode.set_mode(Mode.NETWORKED_UNPAIRED)
    except ModeError as exc:
        raise ValidationError(str(exc)) from exc
    return mode_status_for_request(runtime.mode_status(), request)


@router.post("/solo", response_model=dict[str, Any])
async def return_to_solo(request: Request) -> dict[str, Any]:
    require_local_operator(request)
    runtime = get_runtime(request)
    runtime.mode.set_mode(Mode.SOLO)
    return mode_status_for_request(runtime.mode_status(), request)


@router.post("/tunnel/retry", response_model=dict[str, Any])
@router.post("/retry-tunnel", response_model=dict[str, Any])
async def retry_tunnel(request: Request) -> dict[str, Any]:
    """Retry the local Quick Tunnel without changing the pairing invitation."""

    require_local_operator(request)
    runtime = get_runtime(request)
    if runtime.network is None or not runtime.settings.tunnel_enabled:
        raise ValidationError("Cloudflare Quick Tunnel is not enabled")
    if runtime.mode.mode is Mode.SOLO:
        raise ValidationError("NETWORKED mode must be active before retrying the tunnel")
    runtime.network.retry_tunnel()
    return mode_status_for_request(runtime.mode_status(), request)


@router.post("/set", response_model=dict[str, Any])
async def set_mode(request: Request, body: ModeSetRequest) -> dict[str, Any]:
    require_local_operator(request)
    runtime = get_runtime(request)
    try:
        runtime.mode.set_mode(body.mode)
    except (ModeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    return mode_status_for_request(runtime.mode_status(), request)


@router.get("/pairing", response_model=dict[str, Any])
async def pairing_status(request: Request) -> dict[str, Any]:
    return mode_status_for_request(get_runtime(request).mode_status(), request)


@router.post("/pair", response_model=dict[str, Any])
async def pair_controller(
    request: Request,
    response: Response,
    body: PairingRequest,
) -> dict[str, Any]:
    runtime = get_runtime(request)
    try:
        result = runtime.mode.pair(
            body.code,
            device_name=body.device_name,
            client_id=body.client_id,
        )
    except PairingError as exc:
        raise ValidationError(str(exc)) from exc
    # Pairing changes the mode and can trigger the tunnel listener. Read the
    # enriched runtime snapshot so the phone receives current transport state
    # rather than the mode service's transport-free intermediate snapshot.
    result["status"] = mode_status_for_request(runtime.mode_status(), request)
    response.set_cookie(
        CONTROLLER_COOKIE,
        result["session_token"],
        max_age=max(1, int(result["lease"]["expires_in_seconds"])),
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="strict",
        path="/",
    )
    return result


@router.post("/takeover", response_model=dict[str, Any])
async def takeover_controller(
    request: Request,
    body: DeviceRequest | None = None,
) -> dict[str, Any]:
    require_local_operator(request)
    runtime = get_runtime(request)
    return mode_status_for_request(runtime.mode.takeover_controller(), request)


@router.post("/disconnect", response_model=dict[str, Any])
async def disconnect_controller(request: Request, response: Response) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_controller(runtime, request)
    try:
        status = runtime.mode.disconnect(controller_token(request))
    except PairingAuthenticationError as exc:
        raise _controller_error(exc) from exc
    response.delete_cookie(CONTROLLER_COOKIE, path="/", samesite="strict")
    return mode_status_for_request(status, request)


@router.post("/heartbeat", response_model=dict[str, Any])
async def heartbeat_controller(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_controller(runtime, request)
    try:
        status = runtime.mode.heartbeat(controller_token(request))
    except PairingAuthenticationError as exc:
        raise _controller_error(exc) from exc
    return mode_status_for_request(status, request)


@router.post("/controller/crop", response_model=dict[str, Any])
@router.post("/crop", response_model=dict[str, Any])
@router.post("/classify-crop", response_model=dict[str, Any])
async def classify_controller_crop(
    request: Request,
    file: UploadFile = File(...),
    crop_hash: str | None = Form(default=None, max_length=128),
    width: int | None = Form(default=None, ge=1, le=10000),
    height: int | None = Form(default=None, ge=1, le=10000),
    client_request_id: str | None = Form(default=None, max_length=120),
) -> dict[str, Any]:
    """Classify one bounded browser crop, including a stability-gated live sample."""

    runtime = get_runtime(request)
    lease = require_controller(runtime, request)
    maximum = runtime.settings.max_remote_crop_upload_bytes
    payload = await file.read(maximum + 1)
    if not payload:
        raise ValidationError("the controller crop is empty")
    if len(payload) > maximum:
        raise ValidationError("the controller crop exceeds the configured upload limit")
    actual_hash = hashlib.sha256(payload).hexdigest()
    if crop_hash is not None and crop_hash.strip().lower() != actual_hash:
        raise ValidationError("controller crop hash does not match the uploaded bytes")
    image = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.ndim != 3 or image.shape[0] <= 0 or image.shape[1] <= 0:
        raise ValidationError("the controller crop could not be decoded as an image")
    actual_height, actual_width = image.shape[:2]
    if width is not None and width != actual_width:
        raise ValidationError("controller crop width does not match the uploaded image")
    if height is not None and height != actual_height:
        raise ValidationError("controller crop height does not match the uploaded image")
    request_id = _request_id(client_request_id)
    try:
        # The external path is serialized inside ScanService because there is
        # one active controller. Keep this bounded sample write/classification
        # together in the request task so retry ordering stays deterministic
        # without creating a second inference owner.
        run = runtime.scan.classify_external_crop(
            payload,
            image=image,
            request_id=request_id,
            controller_lease_id=lease.lease_id,
            commit_guard=lambda action: runtime.mode.commit_for_lease(
                lease.lease_id,
                action,
            ),
            on_commit=lambda committed: runtime.mode.record_result(committed.to_dict()),
        )
    except PairingAuthenticationError as exc:
        raise _controller_error(exc) from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise ValidationError(str(exc)) from exc
    public_run = _public_run(run.to_dict())
    return {
        "ok": True,
        "request_id": run.request_id,
        "crop": {
            "sha256": actual_hash,
            "width": actual_width,
            "height": actual_height,
            "bytes": len(payload),
        },
        "classification": public_run,
        "mode": mode_status_for_request(runtime.mode_status(), request),
    }


def _controller_error(exc: Exception) -> ControllerAuthorizationError:
    return ControllerAuthorizationError(str(exc))


def _request_id(value: str | None) -> str:
    if value is None or not value.strip():
        return "controller-" + uuid.uuid4().hex[:12]
    return " ".join(value.strip().split())[:120]


def _public_run(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["crop_path"] = None
    capture = result.get("capture")
    if isinstance(capture, dict):
        capture = dict(capture)
        capture["path"] = None
        result["capture"] = capture
    return result


__all__ = ["router"]
