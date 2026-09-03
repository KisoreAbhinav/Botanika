"""Capability reporting endpoint."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from botanika.api.runtime import build_runtime_capabilities, get_runtime

router = APIRouter(prefix="/capabilities", tags=["capabilities"])


@router.get("", response_model=dict[str, Any])
async def capabilities(request: Request) -> dict[str, Any]:
    return build_runtime_capabilities(get_runtime(request)).to_dict()
