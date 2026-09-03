"""Liveness and readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request

from botanika.api.runtime import APP_VERSION, build_runtime_capabilities, get_runtime
from botanika.api.schemas import HealthResponse, ReadyResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok", version=APP_VERSION)


@router.get("/ready", response_model=ReadyResponse)
async def readiness(request: Request) -> ReadyResponse:
    runtime = get_runtime(request)
    report = build_runtime_capabilities(runtime)
    return ReadyResponse(
        status="ok" if report.ready else "degraded",
        capabilities=report.to_dict(),
    )
