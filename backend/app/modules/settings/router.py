from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_admin_user, get_current_user, request_meta
from app.models import SystemSetting, User, UserSettings
from app.modules.github import provider as github
from app.modules.redmine import provider as redmine
from app.modules.users.dependencies import get_current_user_settings
from app.schemas import (
    IntegrationStatusItem,
    IntegrationStatusResponse,
    IntegrationTestResponse,
    SystemSettingsOut,
    SystemSettingsUpdate,
)
from app.modules.audit.service import write_audit_log
from app.modules.settings.service import SYSTEM_SETTING_KEYS, get_system_settings_map, validate_system_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/system", response_model=SystemSettingsOut)
def get_system_settings(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> SystemSettingsOut:
    return SystemSettingsOut(values=get_system_settings_map(db))


@router.put("/system", response_model=SystemSettingsOut)
def update_system_settings(
    payload: SystemSettingsUpdate,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> SystemSettingsOut:
    before = get_system_settings_map(db)
    try:
        validated_values = validate_system_settings(payload.values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    for key, value in validated_values.items():
        if key not in SYSTEM_SETTING_KEYS:
            continue
        row = db.get(SystemSetting, key)
        if not row:
            row = SystemSetting(key=key)
            db.add(row)
        row.value = value
        row.updated_by = actor.username
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=actor,
        action="update_system_settings",
        target_type="system_settings",
        target_id="global",
        payload_before=before,
        payload_after=validated_values,
        **meta,
    )
    db.commit()
    return SystemSettingsOut(values=get_system_settings_map(db))


@router.get("/integrations/status", response_model=IntegrationStatusResponse)
def get_integration_status(
    _: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> IntegrationStatusResponse:
    settings = get_system_settings_map(db)
    items = [
        IntegrationStatusItem(
            service="redmine_jp",
            configured=bool(settings.get("redmine_jp_host") and user_settings.redmine_jp_api_key_enc),
            connected=False,
            message="Ready to test" if settings.get("redmine_jp_host") and user_settings.redmine_jp_api_key_enc else "Missing host or API key",
        ),
        IntegrationStatusItem(
            service="redmine_vn",
            configured=bool(settings.get("redmine_vn_host") and user_settings.redmine_vn_api_key_enc),
            connected=False,
            message="Ready to test" if settings.get("redmine_vn_host") and user_settings.redmine_vn_api_key_enc else "Missing host or API key",
        ),
        IntegrationStatusItem(
            service="github",
            configured=bool(settings.get("git_repo") and user_settings.github_token_enc),
            connected=False,
            message="Ready to test" if settings.get("git_repo") and user_settings.github_token_enc else "Missing repo or token",
        ),
    ]
    return IntegrationStatusResponse(items=items)


@router.post("/integrations/test/{service_name}", response_model=IntegrationTestResponse)
def test_integration(
    service_name: str,
    _: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> IntegrationTestResponse:
    settings = get_system_settings_map(db)
    try:
        if service_name == "redmine_jp":
            message = redmine.test_connection(settings.get("redmine_jp_host"), user_settings.redmine_jp_api_key_enc)
        elif service_name == "redmine_vn":
            message = redmine.test_connection(settings.get("redmine_vn_host"), user_settings.redmine_vn_api_key_enc)
        elif service_name == "github":
            message = github.test_connection(settings.get("git_repo"), user_settings.github_token_enc)
        else:
            raise HTTPException(status_code=404, detail="Unknown integration service")
    except (redmine.IntegrationConfigError, redmine.RedmineClientError, github.IntegrationConfigError, github.GitHubClientError) as exc:
        return IntegrationTestResponse(service=service_name, success=False, message=str(exc))
    return IntegrationTestResponse(service=service_name, success=True, message=message)
