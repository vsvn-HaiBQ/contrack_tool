from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Query as SAQuery, Session

from app.db import get_db
from app.dependencies import get_admin_user, get_current_user, request_meta
from app.models import AuditLog, User
from app.modules.audit.service import write_audit_log
from app.schemas import AuditDeleteRequest, AuditEventCreateRequest, AuditLogListResponse, AuditLogOptionsResponse, AuditLogOut, MessageResponse

router = APIRouter(prefix="/audit", tags=["audit"])


def _filtered_query(
    db: Session,
    *,
    action: str | None = None,
    actor_username: str | None = None,
    target_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> SAQuery:
    query = db.query(AuditLog)
    if action and action.strip():
        query = query.filter(AuditLog.action.ilike(f"%{action.strip()}%"))
    if actor_username and actor_username.strip():
        query = query.filter(AuditLog.actor_username.ilike(f"%{actor_username.strip()}%"))
    if target_type and target_type.strip():
        query = query.filter(AuditLog.target_type.ilike(f"%{target_type.strip()}%"))
    if date_from:
        query = query.filter(AuditLog.created_at >= date_from)
    if date_to:
        query = query.filter(AuditLog.created_at <= date_to)
    return query


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    action: str | None = None,
    actor_username: str | None = None,
    target_type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    query = _filtered_query(
        db,
        action=action,
        actor_username=actor_username,
        target_type=target_type,
        date_from=date_from,
        date_to=date_to,
    )
    total = query.count()
    rows = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()
    return AuditLogListResponse(
        items=[AuditLogOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/options", response_model=AuditLogOptionsResponse)
def list_audit_options(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> AuditLogOptionsResponse:
    actions = [row[0] for row in db.query(AuditLog.action).distinct().order_by(AuditLog.action.asc()).all() if row[0]]
    actor_usernames = [
        row[0]
        for row in db.query(AuditLog.actor_username).distinct().order_by(AuditLog.actor_username.asc()).all()
        if row[0]
    ]
    target_types = [
        row[0]
        for row in db.query(AuditLog.target_type).distinct().order_by(AuditLog.target_type.asc()).all()
        if row[0]
    ]
    return AuditLogOptionsResponse(actions=actions, actor_usernames=actor_usernames, target_types=target_types)


@router.post("/events", response_model=MessageResponse)
def create_audit_event(
    payload: AuditEventCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    write_audit_log(
        db,
        actor=user,
        action=payload.action.strip(),
        target_type=payload.target_type.strip(),
        target_id=payload.target_id.strip() if payload.target_id and payload.target_id.strip() else None,
        payload_after=payload.payload_after,
        **request_meta(request),
    )
    db.commit()
    return MessageResponse(message="Audit event recorded")


@router.delete("", response_model=MessageResponse)
def delete_audit_logs(
    payload: AuditDeleteRequest,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    query = db.query(AuditLog)
    if payload.ids:
        query = query.filter(AuditLog.id.in_(payload.ids))
    else:
        query = _filtered_query(
            db,
            action=payload.action,
            actor_username=payload.actor_username,
            target_type=payload.target_type,
            date_from=payload.date_from,
            date_to=payload.date_to,
        )
    count = query.delete(synchronize_session=False)
    write_audit_log(
        db,
        actor=actor,
        action="delete_audit_logs",
        target_type="audit_log",
        target_id=None,
        payload_after={"deleted_count": count, **payload.model_dump(exclude_none=True)},
        **request_meta(request),
    )
    db.commit()
    return MessageResponse(message=f"Deleted {count} audit log(s)")
