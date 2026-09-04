"""Read-only species catalog and grounded offline knowledge routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request

from botanika.api.auth import require_local_or_controller
from botanika.api.concurrency import run_blocking
from botanika.api.runtime import get_runtime
from botanika.api.schemas import ChatRequest, ChatResponse, SpeciesListResponse
from botanika.core.errors import NotFoundError


router = APIRouter(tags=["species", "knowledge"])


@router.get("/species", response_model=SpeciesListResponse)
async def list_species(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    category: str | None = Query(default=None, max_length=100),
) -> SpeciesListResponse:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    values = runtime.knowledge.list_species(query=q, category=category)
    return SpeciesListResponse(
        species=[_public_species(runtime, item) for item in values],
        total=len(values),
        catalog={
            "catalog_id": runtime.knowledge.catalog.catalog_id,
            "version": runtime.knowledge.catalog.version,
            "region": runtime.knowledge.catalog.region,
            "digest": runtime.knowledge.catalog.digest,
        },
    )


@router.get("/species/search", response_model=SpeciesListResponse)
async def search_species(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
) -> SpeciesListResponse:
    return await list_species(request, q=q, category=None)


@router.get("/species/{species_id}")
async def species_details(request: Request, species_id: str) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    species = runtime.knowledge.get_species(species_id)
    if species is None:
        raise NotFoundError("species is not in the local catalog")
    return _public_species(runtime, species)


@router.get("/knowledge/search")
async def search_knowledge(
    request: Request,
    q: str = Query(min_length=1, max_length=1000),
    species_id: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=5, ge=1, le=20),
) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    hits = runtime.knowledge.search(q, species_id=species_id, limit=limit)
    return {"query": q, "hits": [hit.to_dict() for hit in hits]}


@router.get("/knowledge/status")
async def knowledge_status(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    return {
        "catalog": {
            "catalog_id": runtime.knowledge.catalog.catalog_id,
            "version": runtime.knowledge.catalog.version,
            "region": runtime.knowledge.catalog.region,
            "digest": runtime.knowledge.catalog.digest,
        },
        "ingestion": runtime.knowledge.ingestion_status(),
        "manifest_digest": runtime.knowledge.knowledge_manifest()["manifest_digest"],
        "fts5": True,
        "citations": "source/license metadata is retained per chunk",
        "local_llm": runtime.llm.status().to_dict() if getattr(runtime, "llm", None) is not None else None,
    }


@router.get("/knowledge/manifest")
async def knowledge_manifest(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    return runtime.knowledge.knowledge_manifest()


@router.post("/chat", response_model=ChatResponse)
async def grounded_chat(request: Request, body: ChatRequest) -> ChatResponse:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    result, engine = await run_blocking(
        _grounded_answer,
        runtime,
        body.question,
        context_species_id=body.context_species_id,
    )
    playback = None
    voice = getattr(runtime, "voice", None)
    if body.speak and voice is not None and not result.abstained:
        try:
            playback = await run_blocking(voice.speak, result.answer)
        except Exception as exc:
            playback = {"status": "unavailable", "detail": str(exc), "played": False}
    return ChatResponse(
        answer=result.answer,
        citations=[item.to_dict() for item in result.citations],
        evidence=[item.to_dict() for item in result.evidence],
        abstained=result.abstained,
        engine=engine,
        playback=playback,
    )


def _grounded_answer(runtime, question: str, *, context_species_id: str | None = None):
    result = runtime.knowledge.answer(question, context_species_id=context_species_id)
    llm = getattr(runtime, "llm", None)
    if result.abstained or llm is None:
        return result, "offline-extractive"
    try:
        status = llm.status()
        generated = llm.generate(question, result.evidence) if status.available else None
    except Exception:
        generated = None
    if not generated:
        return result, "offline-extractive"
    from botanika.knowledge.store import GroundedAnswer

    return GroundedAnswer(generated, result.citations, result.evidence, False), "offline-llm"


def _public_species(runtime, species) -> dict[str, Any]:
    value = species.to_dict()
    value["sources"] = [
        source
        for source_id in species.source_ids
        if (source := runtime.knowledge.source(source_id)) is not None
    ]
    # Knowledge chunks are served as evidence through /knowledge/search and
    # /chat; catalog details contain reviewed facts but not duplicate raw text.
    value.pop("knowledge", None)
    return value
