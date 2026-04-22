from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, request_meta
from app.models import User, UserSettings
from app.modules.redmine import provider as redmine
from app.modules.settings.service import get_system_settings_map
from app.modules.users.dependencies import get_current_user_settings
from app.schemas import LogtimeSourceResponse, LogtimeSaveRequest, LogtimeSaveResult
from app.modules.audit.service import write_audit_log

router = APIRouter(prefix="/logtime", tags=["logtime"])


@router.get("/source", response_model=LogtimeSourceResponse)
def get_logtime_source(
    date: str,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> LogtimeSourceResponse:
    _ = user
    settings = get_system_settings_map(db)
    try:
        rows = redmine.get_logtime_source_resolved(
            settings.get("redmine_vn_host"),
            user_settings.redmine_vn_api_key_enc,
            date,
            project_id=settings.get("redmine_vn_project_id"),
        )
        activities = redmine.list_activities_resolved(settings.get("redmine_vn_host"), user_settings.redmine_vn_api_key_enc)
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return LogtimeSourceResponse(date=date, rows=rows, activities=activities)


@router.post("/save", response_model=list[LogtimeSaveResult])
def save_logtime(
    payload: LogtimeSaveRequest,
    request: Request,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> list[LogtimeSaveResult]:
    settings = get_system_settings_map(db)
    try:
        results = redmine.save_logtime_resolved(
            settings.get("redmine_vn_host"),
            user_settings.redmine_vn_api_key_enc,
            payload.date,
            [row.model_dump() for row in payload.rows],
        )
    except redmine.IntegrationConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="bulk_logtime",
        target_type="logtime",
        target_id=payload.date,
        payload_after=payload.model_dump(),
        **meta,
    )
    db.commit()
    return [LogtimeSaveResult(**item) for item in results]
