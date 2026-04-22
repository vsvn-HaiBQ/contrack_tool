from fastapi import APIRouter, Depends
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import get_db
from app.dependencies import get_current_user
from app.models import User, UserSettings
from app.modules.github import provider as github
from app.modules.redmine import provider as redmine
from app.modules.settings.service import get_system_settings_map

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/detailed")
def health_detailed(db: Session = Depends(get_db)) -> dict:
    checks: dict[str, dict[str, str | bool]] = {"app": {"ok": True, "message": "running"}}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = {"ok": True, "message": "connected"}
    except SQLAlchemyError as exc:
        checks["database"] = {"ok": False, "message": str(exc)}
    try:
        redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        redis_client.ping()
        checks["redis"] = {"ok": True, "message": "connected"}
    except RedisError as exc:
        checks["redis"] = {"ok": False, "message": str(exc)}
    overall = all(bool(item["ok"]) for item in checks.values())
    return {"status": "ok" if overall else "degraded", "checks": checks}


@router.get("/health/integrations")
def health_integrations(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    settings_map = get_system_settings_map(db)
    user_settings = db.get(UserSettings, user.id)
    checks: dict[str, dict[str, str | bool]] = {}
    try:
        message = redmine.test_connection(settings_map.get("redmine_jp_host"), user_settings.redmine_jp_api_key_enc if user_settings else None)
        checks["redmine_jp"] = {"ok": True, "message": message}
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        checks["redmine_jp"] = {"ok": False, "message": str(exc)}
    try:
        message = redmine.test_connection(settings_map.get("redmine_vn_host"), user_settings.redmine_vn_api_key_enc if user_settings else None)
        checks["redmine_vn"] = {"ok": True, "message": message}
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        checks["redmine_vn"] = {"ok": False, "message": str(exc)}
    try:
        message = github.test_connection(settings_map.get("git_repo"), user_settings.github_token_enc if user_settings else None)
        checks["github"] = {"ok": True, "message": message}
    except (github.IntegrationConfigError, github.GitHubClientError) as exc:
        checks["github"] = {"ok": False, "message": str(exc)}
    overall = all(bool(item["ok"]) for item in checks.values())
    return {"status": "ok" if overall else "degraded", "checks": checks}
