from __future__ import annotations

import traceback
from typing import Any

from app.core.celery_app import celery_app
from app.db import SessionLocal
from app.models import User, UserSettings
from app.modules.git_eol.jobs import append_log, update_job
from app.modules.git_eol.service import GitEolError, GitEolService

service = GitEolService()


@celery_app.task(name="git_eol.preview", bind=True)
def preview_task(
    self,  # noqa: ARG001
    *,
    job_id: str,
    user_id: int,
    base_branch: str,
    source_branch: str,
) -> dict[str, Any]:
    update_job(job_id, status="running")

    def emit(level: str, source: str, message: str) -> None:
        append_log(job_id, level=level, source=source, message=message)

    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            raise GitEolError("User no longer exists")

        user_settings = (
            db.query(UserSettings).filter(UserSettings.user_id == user_id).one_or_none()
        )
        encrypted_token = user_settings.github_token_enc if user_settings else None

        from app.modules.settings.service import get_system_settings_map

        repo = get_system_settings_map(db).get("git_repo")
        if not repo:
            raise GitEolError("git_repo is not configured")

        emit("info", "system", f"Job {job_id} started for user={user.username} repo={repo}")
        result = service.preview(
            repo=repo,
            encrypted_token=encrypted_token,
            user=user,
            base_branch=base_branch,
            source_branch=source_branch,
            log=emit,
        )
        payload = result.model_dump()
        update_job(job_id, status="succeeded", result=payload)
        emit("info", "system", "Preview completed successfully")
        return payload
    except GitEolError as exc:
        emit("error", "system", f"Preview failed: {exc}")
        update_job(job_id, status="failed", error=str(exc))
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        emit("error", "system", f"Unexpected error: {exc}")
        emit("error", "system", traceback.format_exc())
        update_job(job_id, status="failed", error=str(exc))
        raise
    finally:
        db.close()
