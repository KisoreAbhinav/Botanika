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
from botanika.mode import PairingAuthenticationError


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
    usage = runtime.library.usage()
    progress = runtime.library.progress(runtime.knowledge.catalog.species)
    aggregate = runtime.library.aggregate_summary(runtime.knowledge.catalog.species)
    payload = [_record_payload(record) for record in records]
    return LibraryListResponse(
        records=payload,
        total=len(payload),
        is_demo_only=False,
        species_count=len(groups),
        observation_count=len(payload),
        categories=runtime.library.categories(),
        coverage={
            "location_available": False,
            "message": "Location unavailable — discoveries are still saved.",
            "species": len(groups),
            "observations": len(payload),
            "storage_bytes": usage["bytes"],
            "supported_species": progress["supported_species"],
            "discovered_species": progress["discovered_species"],
            "coverage_percent": progress["coverage_percent"],
        },
        groups=[_group_payload(group) for group in groups],
        progress=progress,
        aggregate=aggregate,
    )


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
    return value


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
