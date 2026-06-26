from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_admin_user, get_current_user, request_meta
from app.models import User
from app.modules.audit.service import write_audit_log
from app.modules.versions import service as versions_service
from app.schemas import (
    MessageResponse,
    PinVersionRequest,
    VersionIn,
    VersionListResponse,
    VersionOut,
    VersionUpdate,
)

router = APIRouter(prefix="/versions", tags=["versions"])


@router.get("", response_model=VersionListResponse)
def list_versions(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> VersionListResponse:
    rows = versions_service.list_versions(db)
    return VersionListResponse(items=[VersionOut(**versions_service.serialize(row)) for row in rows])


@router.post("", response_model=VersionOut)
def create_version(
    payload: VersionIn,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> VersionOut:
    try:
        row = versions_service.create_version(db, payload.model_dump(exclude_unset=True), actor_username=actor.username)
    except versions_service.VersionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    after = versions_service.serialize(row)
    write_audit_log(
        db,
        actor=actor,
        action="create_version",
        target_type="version",
        target_id=str(row.id),
        payload_after=after,
        **request_meta(request),
    )
    db.commit()
    db.refresh(row)
    return VersionOut(**versions_service.serialize(row))


@router.put("/{version_id}", response_model=VersionOut)
def update_version(
    version_id: int,
    payload: VersionUpdate,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> VersionOut:
    row = versions_service.get_version(db, version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    before = versions_service.serialize(row)
    try:
        versions_service.update_version(db, row, payload.model_dump(exclude_unset=True), actor_username=actor.username)
    except versions_service.VersionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    after = versions_service.serialize(row)
    write_audit_log(
        db,
        actor=actor,
        action="update_version",
        target_type="version",
        target_id=str(row.id),
        payload_before=before,
        payload_after=after,
        **request_meta(request),
    )
    db.commit()
    db.refresh(row)
    return VersionOut(**versions_service.serialize(row))


@router.delete("/{version_id}", response_model=MessageResponse)
def delete_version(
    version_id: int,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    row = versions_service.get_version(db, version_id)
    if not row:
        raise HTTPException(status_code=404, detail="Version not found")
    before = versions_service.serialize(row)
    versions_service.delete_version(db, row)
    write_audit_log(
        db,
        actor=actor,
        action="delete_version",
        target_type="version",
        target_id=str(version_id),
        payload_before=before,
        **request_meta(request),
    )
    db.commit()
    return MessageResponse(message=f"Deleted version {before['name']}")


@router.post("/pin", response_model=VersionOut | None)
def pin_version(
    payload: PinVersionRequest,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VersionOut | None:
    try:
        settings = versions_service.pin_version(db, actor.id, payload.version_id)
    except versions_service.VersionValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    if not settings.pinned_version_id:
        return None
    row = versions_service.get_version(db, settings.pinned_version_id)
    return VersionOut(**versions_service.serialize(row)) if row else None
