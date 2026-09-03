"""Pydantic request/response schemas for the Phase 6 local API."""

from __future__ import annotations

from typing import Any

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


class LibrarySaveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class LibraryNoteRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class SpeciesListResponse(BaseModel):
    species: list[dict[str, Any]]
    total: int
    catalog: dict[str, Any]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    context_species_id: str | None = None


class ChatResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    abstained: bool


class DiagnosticsLogEntry(BaseModel):
    logged_at: float
    request_id: str
    method: str
    path: str
    status: int
    duration_ms: float
