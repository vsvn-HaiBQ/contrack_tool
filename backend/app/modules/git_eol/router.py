import json
from typing import Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, get_optional_user, request_meta
from app.models import User, UserSettings
from app.modules.audit.service import write_audit_log
from app.modules.git_eol.jobs import (
    create_job,
    get_job,
    get_logs,
    new_job_id,
    stream_events,
)
from app.modules.git_eol.schemas import (
    GitEolCommitRequest,
    GitEolCommitResponse,
    GitEolDiffResponse,
    GitEolFixRequest,
    GitEolFixResponse,
    GitEolJobLog,
    GitEolJobResponse,
    GitEolJobStatus,
    GitEolPreviewRequest,
    GitEolPreviewResponse,
    GitEolPushRequest,
    GitEolPushResponse,
    GitEolStructuredDiffResponse,
)
from app.modules.git_eol.service import GitEolError, GitEolService
from app.modules.git_eol.tasks import preview_task
from app.modules.settings.service import get_system_settings_map
from app.modules.users.dependencies import get_current_user_settings

router = APIRouter(prefix="/git-eol", tags=["git-eol"])
service = GitEolService()


def _repo(db: Session) -> str:
    repo = get_system_settings_map(db).get("git_repo")
    if not repo:
        raise HTTPException(status_code=400, detail="git_repo is not configured")
    return repo


def _job_to_response(payload: dict) -> GitEolJobResponse:
    result_obj = payload.get("result")
    return GitEolJobResponse(
        job_id=payload["job_id"],
        kind=payload.get("kind", ""),
        status=payload.get("status", "queued"),
        error=payload.get("error"),
        result=GitEolPreviewResponse(**result_obj) if result_obj else None,
    )


@router.post("/preview", response_model=GitEolJobStatus)
def enqueue_preview(
    payload: GitEolPreviewRequest,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),  # noqa: ARG001 - validates configured
    db: Session = Depends(get_db),
) -> GitEolJobStatus:
    _repo(db)  # validate config eagerly
    job_id = new_job_id()
    create_job(
        job_id,
        user_id=user.id,
        kind="preview",
        params={"base_branch": payload.base_branch, "source_branch": payload.source_branch},
    )
    preview_task.delay(
        job_id=job_id,
        user_id=user.id,
        base_branch=payload.base_branch,
        source_branch=payload.source_branch,
    )
    return GitEolJobStatus(job_id=job_id, kind="preview", status="queued")


@router.get("/jobs/{job_id}", response_model=GitEolJobResponse)
def fetch_job(job_id: str, user: User = Depends(get_current_user)) -> GitEolJobResponse:
    payload = get_job(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    if payload.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Job belongs to another user")
    return _job_to_response(payload)


@router.get("/jobs/{job_id}/logs", response_model=list[GitEolJobLog])
def fetch_job_logs(job_id: str, user: User = Depends(get_current_user)) -> list[GitEolJobLog]:
    payload = get_job(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    if payload.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Job belongs to another user")
    return [GitEolJobLog(**entry) for entry in get_logs(job_id)]


@router.get("/jobs/{job_id}/stream")
def stream_job(
    job_id: str,
    user: User | None = Depends(get_optional_user),
) -> StreamingResponse:
    payload = get_job(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Job not found")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if payload.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Job belongs to another user")

    def event_generator() -> Iterator[bytes]:
        try:
            for event in stream_events(job_id):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")
        except GeneratorExit:
            return
        except Exception as exc:  # noqa: BLE001
            err = json.dumps({"type": "error", "message": str(exc)})
            yield f"data: {err}\n\n".encode("utf-8")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions/{session_id}/diff", response_model=GitEolDiffResponse)
def fetch_diff(
    session_id: str,
    path: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
) -> GitEolDiffResponse:
    try:
        diff = service.unified_diff(user=user, session_id=session_id, path=path)
    except GitEolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GitEolDiffResponse(session_id=session_id, path=path, diff=diff)


@router.get("/sessions/{session_id}/sxs-diff", response_model=GitEolStructuredDiffResponse)
def fetch_structured_diff(
    session_id: str,
    path: str = Query(..., min_length=1),
    user: User = Depends(get_current_user),
) -> GitEolStructuredDiffResponse:
    try:
        result = service.structured_diff(user=user, session_id=session_id, path=path)
    except GitEolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GitEolStructuredDiffResponse(session_id=session_id, **result)


@router.post("/fix", response_model=GitEolFixResponse)
def fix_git_eol(
    payload: GitEolFixRequest,
    user: User = Depends(get_current_user),
) -> GitEolFixResponse:
    try:
        return service.fix(user=user, session_id=payload.session_id, selected_files=payload.files)
    except GitEolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/commit", response_model=GitEolCommitResponse)
def commit_git_eol(
    payload: GitEolCommitRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GitEolCommitResponse:
    try:
        result = service.commit(user=user, session_id=payload.session_id, message=payload.message)
    except GitEolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result["committed"]:
        write_audit_log(
            db,
            actor=user,
            action="git_eol_commit",
            target_type="git_commit",
            target_id=result["commit_sha"],
            payload_after={"session_id": payload.session_id, "files": result["changed_files"]},
            **request_meta(request),
        )
        db.commit()
    return GitEolCommitResponse(**result)


@router.post("/push", response_model=GitEolPushResponse)
def push_git_eol(
    payload: GitEolPushRequest,
    request: Request,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> GitEolPushResponse:
    try:
        result = service.push(user=user, session_id=payload.session_id, encrypted_token=user_settings.github_token_enc)
    except GitEolError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_audit_log(
        db,
        actor=user,
        action="git_eol_push",
        target_type="git_branch",
        target_id=result["source_branch"],
        payload_after={"session_id": payload.session_id, "message": result["message"]},
        **request_meta(request),
    )
    db.commit()
    return GitEolPushResponse(**result)
