"""Authoritative species-grouped discovery library routes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, File, Query, Request, UploadFile
from fastapi.responses import FileResponse

from botanika.api.auth import require_local_or_controller
from botanika.api.runtime import get_runtime
from botanika.api.schemas import (
    LibraryListResponse,
    LibraryNoteRequest,
    LibrarySaveRequest,
    LibrarySaveResponse,
    OkResponse,
)
from botanika.core.errors import ControllerAuthorizationError, NotFoundError, ValidationError
from botanika.knowledge import REGIONAL_CATEGORIES, RegionalCatalogError, load_regional_catalog
from botanika.mode import PairingAuthenticationError
from botanika.storage import category_color


router = APIRouter(prefix="/library", tags=["library"])


@router.get("/records", response_model=LibraryListResponse)
async def list_records(
    request: Request,
    category: str | None = Query(default=None, max_length=100),
) -> LibraryListResponse:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        records = runtime.library.list_records()
        return LibraryListResponse(
            records=[record.to_dict() for record in records],
            total=len(records),
            is_demo_only=True,
        )
    records = runtime.library.list_records(category=category)
    groups = runtime.library.list_grouped(category=category)
    locations = runtime.library.list_locations(category=category)
    usage = runtime.library.usage()
    progress = runtime.library.progress(runtime.knowledge.catalog.species)
    aggregate = runtime.library.aggregate_summary(runtime.knowledge.catalog.species)
    regional = _regional_payload(runtime, records, groups)
    map_payload = _map_payload(locations, regional_catalog=regional["catalog"])
    payload = [_record_payload(record) for record in records]
    return LibraryListResponse(
        records=payload,
        total=len(payload),
        is_demo_only=False,
        species_count=len(groups),
        observation_count=len(payload),
        categories=runtime.library.categories(),
        coverage={
            "location_available": bool(locations),
            "message": (
                f"{len(locations)} observation location(s) recorded."
                if locations
                else "Location unavailable — discoveries are still saved."
            ),
            "species": len(groups),
            "observations": len(payload),
            "locations": len(locations),
            "storage_bytes": usage["bytes"],
            "supported_species": progress["supported_species"],
            "discovered_species": progress["discovered_species"],
            "coverage_percent": progress["coverage_percent"],
        },
        groups=[_group_payload(group) for group in groups],
        progress=progress,
        aggregate=aggregate,
        map=map_payload,
        map_legend=map_payload["legend"],
        regional_catalog=regional["catalog"],
        regional_checklist=regional["species"],
    )


@router.get("/map")
async def library_map(request: Request) -> dict[str, Any]:
    """Return observation markers and an accessible category legend."""

    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        return {
            "locations": [],
            "total": 0,
            "has_locations": False,
            "message": "Map locations are available for real discoveries only.",
            "legend": [],
        }
    regional = _load_regional(runtime)
    locations = runtime.library.list_locations()
    return _map_payload(locations, regional_catalog=regional)


@router.get("/map/export")
async def export_library_map(request: Request) -> dict[str, Any]:
    """Export map markers as portable JSON without exposing media files."""

    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        return {
            "format": "botanika-plant-map-1",
            "locations": [],
            "legend": [],
            "message": "Map export is available for real discoveries only.",
        }
    regional = _load_regional(runtime)
    payload = _map_payload(runtime.library.list_locations(), regional_catalog=regional)
    return {
        "format": "botanika-plant-map-1",
        "region": payload["region"],
        "scope_note": payload["scope_note"],
        "legend": payload["legend"],
        "locations": payload["locations"],
    }


@router.get("/region")
async def regional_library_catalog(request: Request) -> dict[str, Any]:
    """Return found/not-found status against the wider Vellore checklist."""

    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        return {
            "catalog": {},
            "species": [],
            "total": 0,
            "found": 0,
            "not_found": 0,
        }
    records = runtime.library.list_records()
    groups = runtime.library.list_grouped()
    regional = _regional_payload(runtime, records, groups)
    value = dict(regional)
    value["total"] = len(regional["species"])
    value["found"] = sum(1 for item in regional["species"] if item["status"] == "found")
    value["not_found"] = value["total"] - value["found"]
    return value


@router.get("/species/{species_id}")
async def library_species_details(request: Request, species_id: str) -> dict[str, Any]:
    """Return one deduplicated species entry with all observations/locations."""

    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        raise NotFoundError("species details are available for real discoveries only")
    groups = runtime.library.list_grouped()
    group = next((item for item in groups if item.get("species_id") == species_id), None)
    if group is not None:
        return _group_payload(group)
    regional = _regional_payload(runtime, [], groups)
    checklist = next((item for item in regional["species"] if item.get("species_id") == species_id), None)
    if checklist is None:
        raise NotFoundError("species is not in the local library or regional checklist")
    return checklist


@router.get("/progress")
async def library_progress(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        return {"supported_species": 0, "discovered_species": 0, "coverage_percent": 0.0, "category_progress": [], "milestones": []}
    return runtime.library.progress(runtime.knowledge.catalog.species)


@router.get("/aggregate")
async def library_aggregate(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        return {"anonymous": True, "scope": "this-device", "transport": "local-only", "personal_identifiers_included": False}
    return runtime.library.aggregate_summary(runtime.knowledge.catalog.species)


@router.post("/records", response_model=LibrarySaveResponse)
async def save_record(
    request: Request,
    body: LibrarySaveRequest | None = None,
) -> LibrarySaveResponse:
    runtime = get_runtime(request)
    lease = require_local_or_controller(runtime, request)

    def persist():
        snapshot = _snapshot_for_save(runtime, body, lease)
        if runtime.settings.legacy_demo_mode:
            return runtime.library.save(
                snapshot.capture,
                snapshot.classification,
                request_name="scan",
            )
        return runtime.library.save(
            snapshot.capture,
            snapshot.classification,
            request_name="scan",
            note=body.note if body is not None else None,
            position=(
                _position_payload(body.position)
                if body is not None and body.position is not None
                else None
            ),
        )

    try:
        record = (
            runtime.mode.commit_for_lease(lease.lease_id, persist)
            if lease is not None
            else persist()
        )
    except PairingAuthenticationError as exc:
        raise ControllerAuthorizationError(str(exc)) from exc
    except (ValueError, OSError, RuntimeError) as exc:
        raise ValidationError(str(exc)) from exc
    return LibrarySaveResponse(
        ok=True,
        record=_record_payload(record, legacy=runtime.settings.legacy_demo_mode),
    )


@router.patch("/records/{record_id}", response_model=LibrarySaveResponse)
async def update_record_note(
    request: Request,
    record_id: str,
    body: LibraryNoteRequest,
) -> LibrarySaveResponse:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        raise ValidationError("notes are available for real discoveries only")
    try:
        record = runtime.library.update_note(record_id, body.note)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    if record is None:
        raise NotFoundError("library observation not found")
    return LibrarySaveResponse(
        ok=True,
        record=_record_payload(record, legacy=get_runtime(request).settings.legacy_demo_mode),
    )


@router.delete("/records/{record_id}", response_model=OkResponse)
async def delete_record(request: Request, record_id: str, confirmed: bool = False) -> OkResponse:
    require_local_or_controller(get_runtime(request), request)
    if not confirmed:
        raise ValidationError("deletion requires explicit confirmation")
    deleted = get_runtime(request).library.delete(record_id, confirmed=True)
    if not deleted:
        raise NotFoundError("library observation not found")
    return OkResponse(detail="observation deleted")


@router.get("/export", response_class=FileResponse)
async def export_library(request: Request) -> FileResponse:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.settings.legacy_demo_mode:
        raise ValidationError("export is available for the real discovery library only")
    destination = runtime.settings.backup_dir / "botanika-library-export.zip"
    path = runtime.library.export_archive(destination)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=path.name,
        headers={"Cache-Control": "no-store"},
    )


@router.get("/backup", response_class=FileResponse)
async def backup_library(request: Request) -> FileResponse:
    return await export_library(request)


@router.post("/restore", response_model=OkResponse)
async def restore_library(
    request: Request,
    confirmed: bool = False,
    file: UploadFile = File(...),
) -> OkResponse:
    require_local_or_controller(get_runtime(request), request)
    if not confirmed:
        raise ValidationError("restoring the library requires explicit confirmation")
    runtime = get_runtime(request)
    if runtime.settings.legacy_demo_mode:
        raise ValidationError("restore is available for the real discovery library only")
    runtime.settings.backup_dir.mkdir(parents=True, exist_ok=True)
    temporary = runtime.settings.backup_dir / f".restore-{uuid.uuid4().hex}.zip"
    try:
        temporary.write_bytes(await file.read())
        runtime.library.restore_archive(temporary, confirmed=True)
        # Archives may come from an older compatible catalog revision. Re-seed
        # the current immutable catalog and FTS data after restoring user
        # discoveries so stale citation metadata never becomes live.
        runtime.knowledge.seed_catalog()
    except (ValueError, OSError, RuntimeError) as exc:
        raise ValidationError(str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)
    return OkResponse(detail="library restored")


def _record_payload(record, *, legacy: bool = False) -> dict[str, Any]:
    value = record.to_dict()
    if legacy or "crop_relative_path" not in value:
        value["crop_url"] = "/media/demo/" + str(record.crop_filename)
        value["thumbnail_url"] = value["crop_url"]
        return value
    value["crop_url"] = "/media/discoveries/" + record.crop_relative_path
    if record.thumbnail_path:
        value["thumbnail_url"] = "/media/discoveries/" + record.thumbnail_path
    else:
        value["thumbnail_url"] = value["crop_url"]
    return value


def _group_payload(group: dict[str, Any]) -> dict[str, Any]:
    value = dict(group)
    if isinstance(value.get("newest"), dict):
        newest = dict(value["newest"])
        relative = newest.get("thumbnail_path") or newest.get("crop_relative_path")
        if relative:
            newest["thumbnail_url"] = "/media/discoveries/" + str(relative)
        value["newest"] = newest
    observations = []
    for observation in value.get("observations", []):
        if not isinstance(observation, dict):
            continue
        item = dict(observation)
        relative = item.get("thumbnail_path") or item.get("crop_relative_path")
        if relative:
            item["thumbnail_url"] = "/media/discoveries/" + str(relative)
        observations.append(item)
    if observations:
        value["observations"] = observations
    return value


def _load_regional(runtime) -> dict[str, Any]:
    try:
        return load_regional_catalog(runtime.settings.regional_catalog_path)
    except RegionalCatalogError as exc:
        raise ValidationError(f"regional catalog unavailable: {exc}") from exc


def _regional_payload(runtime, records, groups) -> dict[str, Any]:
    catalog = _load_regional(runtime)
    groups_by_id = {str(item.get("species_id")): item for item in groups}
    classifier_ids = {item.species_id for item in runtime.knowledge.catalog.species}
    sources_by_id = {str(item["source_id"]): dict(item) for item in catalog["sources"]}
    species: list[dict[str, Any]] = []
    for item in catalog["species"]:
        value = dict(item)
        group = groups_by_id.get(str(item["species_id"]))
        public_group = _group_payload(group) if group else None
        observations = list(public_group.get("observations", [])) if public_group else []
        locations = list(public_group.get("locations", [])) if public_group else []
        value["status"] = "found" if group else "not_found"
        value["found"] = bool(group)
        value["observation_count"] = len(observations)
        value["location_count"] = len(locations)
        value["locations"] = locations
        value["observations"] = observations
        value["photos"] = [
            observation.get("thumbnail_url") or observation.get("crop_url")
            for observation in observations
            if observation.get("thumbnail_url") or observation.get("crop_url")
        ]
        value["category_color"] = category_color(str(item["category"]))
        value["classifier_supported"] = str(item["species_id"]) in classifier_ids
        value["source_details"] = [
            sources_by_id[source_id]
            for source_id in item.get("source_ids", [])
            if source_id in sources_by_id
        ]
        species.append(value)
    return {
        "catalog": {
            "catalog_id": catalog["catalog_id"],
            "version": catalog["version"],
            "region": catalog["region"],
            "scope_note": catalog["scope_note"],
            "occurrence_basis": catalog.get("occurrence_basis", {}),
            "digest": catalog["digest"],
        },
        "species": sorted(species, key=lambda value: str(value["common_name"]).casefold()),
    }


def _map_payload(locations: list[dict[str, Any]], *, regional_catalog: dict[str, Any]) -> dict[str, Any]:
    categories = sorted({str(item.get("category") or "Uncategorized") for item in locations})
    known_categories = list(REGIONAL_CATEGORIES)
    legend_categories = list(dict.fromkeys(known_categories + categories))
    legend = [
        {
            "category": category,
            "color": category_color(category),
            "label": category,
        }
        for category in legend_categories
    ]
    markers: list[dict[str, Any]] = []
    for location in locations:
        marker = dict(location)
        if marker.get("thumbnail_path"):
            marker["thumbnail_url"] = "/media/discoveries/" + str(marker["thumbnail_path"])
        marker["category_color"] = category_color(str(marker.get("category") or ""))
        markers.append(marker)
    return {
        "locations": markers,
        "total": len(markers),
        "has_locations": bool(markers),
        "message": (
            "Markers are observation coordinates; open directions uses an external map."
            if markers
            else "No saved observations include an accurate location yet."
        ),
        "legend": legend,
        "region": regional_catalog.get("region", ""),
        "scope_note": regional_catalog.get("scope_note", ""),
    }


def _snapshot_for_save(runtime, body, lease):
    snapshot = runtime.scan.latest_snapshot()
    if snapshot is None or snapshot.capture is None or snapshot.classification is None:
        raise ValidationError("no accepted crop is currently available to save")
    if lease is not None:
        if body is None or body.request_id is None or body.crop_hash is None:
            raise ValidationError("controller saves require the classified request ID and crop hash")
        if snapshot.controller_lease_id != lease.lease_id:
            raise ValidationError("the accepted crop does not belong to this controller lease")
        if snapshot.classification.request_id != body.request_id:
            raise ValidationError("the accepted crop request is stale")
        if snapshot.classification.crop_hash != body.crop_hash.lower():
            raise ValidationError("the accepted crop hash is stale")
    if not snapshot.classification.result.is_accepted:
        raise ValidationError("only an accepted production result may be saved")
    if runtime.settings.legacy_demo_mode and not snapshot.classification.result.is_stub:
        raise ValidationError("legacy demo mode requires a demo result")
    return snapshot


def _position_payload(position) -> dict[str, object]:
    if hasattr(position, "model_dump"):
        return position.model_dump(exclude_none=True)
    return position.dict(exclude_none=True)
