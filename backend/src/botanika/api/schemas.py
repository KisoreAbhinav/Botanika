"""Pydantic request/response schemas for the Phase 9 local API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str = "botanika-api"
    version: str


class ReadyResponse(BaseModel):
    status: str
    capabilities: dict[str, Any]


class OkResponse(BaseModel):
    ok: bool = True
    detail: str | None = None


class SelectBoxRequest(BaseModel):
    index: int = Field(ge=0)


class FallbackCaptureRequest(BaseModel):
    index: int = Field(default=0, ge=0)


class LibrarySaveResponse(BaseModel):
    ok: bool
    record: dict[str, Any] | None = None
    detail: str | None = None


class LibraryListResponse(BaseModel):
    records: list[dict[str, Any]]
    total: int
    is_demo_only: bool = False
    species_count: int = 0
    observation_count: int = 0
    categories: list[str] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)
    groups: list[dict[str, Any]] = Field(default_factory=list)
    progress: dict[str, Any] = Field(default_factory=dict)
    aggregate: dict[str, Any] = Field(default_factory=dict)
    map: dict[str, Any] = Field(default_factory=dict)
    map_legend: list[dict[str, Any]] = Field(default_factory=list)
    regional_catalog: dict[str, Any] = Field(default_factory=dict)
    regional_checklist: list[dict[str, Any]] = Field(default_factory=list)


class PositionRequest(BaseModel):
    """Optional browser position sampled only at an explicit save action."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(ge=0, le=1_000_000)
    timestamp: float | None = Field(default=None, ge=0)
    source: str = Field(min_length=1, max_length=120)


class LibrarySaveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)
    position: PositionRequest | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=120)
    crop_hash: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class LibraryNoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class SpeciesListResponse(BaseModel):
    species: list[dict[str, Any]]
    total: int
    catalog: dict[str, Any]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    context_species_id: str | None = None
    speak: bool = False


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    abstained: bool
    engine: str = "offline-extractive"
    playback: dict[str, Any] | None = None


class VoiceSpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ModeSetRequest(BaseModel):
    mode: Literal["SOLO", "NETWORKED_UNPAIRED"]


class PairingRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)
    device_name: str = Field(default="Paired browser", min_length=1, max_length=80)
    client_id: str | None = Field(default=None, max_length=120)


class DeviceRequest(BaseModel):
    device_name: str = Field(default="Paired browser", min_length=1, max_length=80)
    client_id: str | None = Field(default=None, max_length=120)


class DiagnosticsLogEntry(BaseModel):
    logged_at: float
    request_id: str
    method: str
    path: str
    status: int
    duration_ms: float
