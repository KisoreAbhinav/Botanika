"""Read-only status for the private AP and optional Quick Tunnel transports."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from botanika.api.auth import require_local_or_controller
from botanika.api.runtime import get_runtime

router = APIRouter(prefix="/network", tags=["network"])


@router.get("/status", response_model=dict[str, Any])
async def network_status(request: Request) -> dict[str, Any]:
    """Return measured AP boundaries plus sanitized tunnel lifecycle state."""

    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    return runtime.network_status()


@router.get("", response_model=dict[str, Any], include_in_schema=False)
async def network_status_alias(request: Request) -> dict[str, Any]:
    """Short alias retained for operators inspecting the service manually."""

    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    return runtime.network_status()
