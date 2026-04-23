import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import settings as app_settings
from app.db import get_db
from app.dependencies import get_admin_user, get_current_user, request_meta
from app.models import User, UserSettings
from app.core.session_store import session_store
from app.modules.users.dependencies import get_current_user_settings
from app.schemas import (
    AssigneeOption,
    ChangePasswordRequest,
    MessageResponse,
    PasswordResetRequest,
    TrackerOption,
    UserCreateRequest,
    UserOut,
    UserSettingsIn,
    UserSettingsOut,
)
from app.modules.users.service import (
    apply_user_settings,
    create_user_record,
    serialize_user_settings,
    update_password,
    validate_password,
    validate_user_settings_input,
    validate_username,
)
from app.core.security import verify_password
from app.modules.audit.service import write_audit_log
from app.modules.redmine import provider as redmine
from app.modules.settings.service import get_system_settings_map

router = APIRouter(prefix="/users", tags=["users"])

# Spec 09: status/activity caches are long-lived (24h) and refreshable by admin.
_LONG_CACHE_TTL_SECONDS = 24 * 60 * 60


def _assignee_cache_key(host: str | None, project_id: str | None) -> str:
    digest = hashlib.sha256(f"{host or ''}:{project_id or ''}".encode("utf-8")).hexdigest()
    return f"cache:redmine_vn_assignees:{digest}"


def _activities_cache_key(host: str | None, encrypted_api_key: str | None) -> str:
    digest = hashlib.sha256(f"{host or ''}:{encrypted_api_key or ''}:activities".encode("utf-8")).hexdigest()
    return f"cache:redmine_vn_activities:{digest}"


def _statuses_cache_key(host: str | None, encrypted_api_key: str | None) -> str:
    digest = hashlib.sha256(f"{host or ''}:{encrypted_api_key or ''}:statuses".encode("utf-8")).hexdigest()
    return f"cache:redmine_vn_statuses:{digest}"


def _trackers_cache_key(host: str | None, encrypted_api_key: str | None, project_id: str | None) -> str:
    digest = hashlib.sha256(f"{host or ''}:{encrypted_api_key or ''}:{project_id or ''}:trackers".encode("utf-8")).hexdigest()
    return f"cache:redmine_vn_trackers:{digest}"


@router.get("", response_model=list[UserOut])
def list_users(_: User = Depends(get_admin_user), db: Session = Depends(get_db)) -> list[User]:
    return db.query(User).order_by(User.username.asc()).all()


@router.post("", response_model=UserOut)
def create_user(
    payload: UserCreateRequest,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> User:
    try:
        username = validate_username(payload.username)
        password = validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(status_code=400, detail="Username already exists")
    user = create_user_record(db, username=username, password=password, role=payload.role)
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=actor,
        action="create_user",
        target_type="user",
        target_id=str(user.id),
        payload_after={"username": user.username, "role": user.role},
        **meta,
    )
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", response_model=MessageResponse)
def delete_user(
    user_id: int,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.username == actor.username:
        raise HTTPException(status_code=400, detail="Cannot delete current user")
    before = {"id": user.id, "username": user.username, "role": user.role}
    db.delete(user)
    meta = request_meta(request)
    write_audit_log(db, actor=actor, action="delete_user", target_type="user", target_id=str(user_id), payload_before=before, **meta)
    db.commit()
    return MessageResponse(message=f"Deleted user {before['username']}")


@router.post("/{user_id}/reset-password", response_model=MessageResponse)
def reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        password = validate_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    update_password(user, password)
    meta = request_meta(request)
    write_audit_log(db, actor=actor, action="reset_password", target_type="user", target_id=str(user_id), **meta)
    db.commit()
    return MessageResponse(message="Password reset")


@router.get("/me/settings", response_model=UserSettingsOut)
def get_my_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserSettingsOut:
    settings = db.get(UserSettings, user.id)
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return serialize_user_settings(settings)


@router.put("/me/settings", response_model=UserSettingsOut)
def update_my_settings(
    payload: UserSettingsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSettingsOut:
    settings = db.get(UserSettings, user.id)
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
    try:
        validated = validate_user_settings_input(
            redmine_jp_api_key=payload.redmine_jp_api_key,
            redmine_vn_api_key=payload.redmine_vn_api_key,
            github_token=payload.github_token,
            default_assignee_id=payload.default_assignee_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    apply_user_settings(
        settings,
        redmine_jp_api_key=validated["redmine_jp_api_key"],
        redmine_vn_api_key=validated["redmine_vn_api_key"],
        github_token=validated["github_token"],
        default_assignee_id=validated["default_assignee_id"],
    )
    db.commit()
    db.refresh(settings)
    return serialize_user_settings(settings)


@router.get("/assignees", response_model=list[AssigneeOption])
def list_assignees(
    user: User = Depends(get_current_user),
    settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> list[AssigneeOption]:
    _ = user
    system_settings = get_system_settings_map(db)
    host = system_settings.get("redmine_vn_host")
    project_id = system_settings.get("redmine_vn_project_id")
    encrypted_api_key = settings.redmine_vn_api_key_enc
    cache_key = _assignee_cache_key(host, project_id)
    try:
        cached = session_store._client().get(cache_key)
        if cached:
            return [AssigneeOption(**assignee) for assignee in json.loads(cached)]
        assignees = redmine.list_assignees_resolved(host, encrypted_api_key, project_id)
        session_store._client().setex(cache_key, _LONG_CACHE_TTL_SECONDS, json.dumps(assignees))
        return [AssigneeOption(**assignee) for assignee in assignees]
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/activities", response_model=list[str])
def list_activities(
    user: User = Depends(get_current_user),
    settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> list[str]:
    _ = user
    system_settings = get_system_settings_map(db)
    host = system_settings.get("redmine_vn_host")
    encrypted_api_key = settings.redmine_vn_api_key_enc
    cache_key = _activities_cache_key(host, encrypted_api_key)
    try:
        cached = session_store._client().get(cache_key)
        if cached:
            return json.loads(cached)
        activities = redmine.list_activities_resolved(host, encrypted_api_key)
        session_store._client().setex(cache_key, _LONG_CACHE_TTL_SECONDS, json.dumps(activities))
        return activities
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/me/change-password", response_model=MessageResponse)
def change_my_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    try:
        new_password = validate_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    update_password(user, new_password)
    meta = request_meta(request)
    write_audit_log(db, actor=user, action="change_password", target_type="user", target_id=str(user.id), **meta)
    db.commit()
    return MessageResponse(message="Password updated")


@router.get("/statuses", response_model=list[dict])
def list_statuses(
    force_refresh: bool = False,
    user: User = Depends(get_current_user),
    settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> list[dict]:
    _ = user
    system_settings = get_system_settings_map(db)
    host = system_settings.get("redmine_vn_host")
    encrypted_api_key = settings.redmine_vn_api_key_enc
    cache_key = _statuses_cache_key(host, encrypted_api_key)
    try:
        if force_refresh:
            client = session_store._client()
            client.delete(cache_key)
            for key in client.scan_iter(match="cache:redmine_issue_payload:*"):
                client.delete(key)
        cached = session_store._client().get(cache_key)
        if cached:
            return json.loads(cached)
        statuses = redmine.list_issue_statuses_resolved(host, encrypted_api_key)
        session_store._client().setex(cache_key, _LONG_CACHE_TTL_SECONDS, json.dumps(statuses))
        return statuses
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/trackers", response_model=list[TrackerOption])
def list_trackers(
    user: User = Depends(get_current_user),
    settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> list[TrackerOption]:
    _ = user
    system_settings = get_system_settings_map(db)
    host = system_settings.get("redmine_vn_host")
    project_id = system_settings.get("redmine_vn_project_id")
    encrypted_api_key = settings.redmine_vn_api_key_enc
    cache_key = _trackers_cache_key(host, encrypted_api_key, project_id)
    try:
        cached = session_store._client().get(cache_key)
        if cached:
            return [TrackerOption(**item) for item in json.loads(cached)]
        trackers = redmine.list_trackers_resolved(host, encrypted_api_key, project_id)
        session_store._client().setex(cache_key, _LONG_CACHE_TTL_SECONDS, json.dumps(trackers))
        return [TrackerOption(**item) for item in trackers]
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cache/refresh", response_model=MessageResponse)
def refresh_caches(
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Admin-only: drop cached assignees/activities/statuses/trackers for all users."""
    _ = db
    client = session_store._client()
    deleted = 0
    for prefix in ("cache:redmine_vn_assignees:*", "cache:redmine_vn_activities:*", "cache:redmine_vn_statuses:*", "cache:redmine_vn_trackers:*", "cache:redmine_issue_payload:*"):
        for key in client.scan_iter(match=prefix):
            client.delete(key)
            deleted += 1
    return MessageResponse(message=f"Cleared {deleted} cache entries (by {actor.username})")
