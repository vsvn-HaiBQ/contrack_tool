from __future__ import annotations

import json
import secrets
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.session_store import session_store
from app.db import get_db
from app.dependencies import get_admin_user, get_current_user, request_meta
from app.models import User, UserSettings
from app.modules.audit.service import write_audit_log
from app.modules.box import service
from app.modules.users.dependencies import get_current_user_settings
from app.schemas import (
    BoxOAuthStartRequest,
    BoxOAuthStartResponse,
    BoxSettingsIn,
    BoxSettingsOut,
    BoxStatusResponse,
    BoxUploadAccessResponse,
)

router = APIRouter(prefix="/box", tags=["box"])

_STATE_TTL_SECONDS = 10 * 60


def _state_key(state: str) -> str:
    return f"box_oauth_state:{state}"


def _resolve_redirect_url(request: Request, explicit_redirect_uri: str | None) -> str:
    if explicit_redirect_uri:
        redirect_url = explicit_redirect_uri.strip()
        parsed = urlparse(redirect_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=400, detail="redirect_uri must be a valid http/https URL")
        if not (parsed.path.rstrip("/").endswith("/api/box/oauth/callback") or
                parsed.path.rstrip("/").endswith("/box/oauth/callback")):
            raise HTTPException(status_code=400, detail="redirect_uri must point to /api/box/oauth/callback or /box/oauth/callback")
        return redirect_url
    return str(request.url_for("box_oauth_callback"))


@router.get("/settings", response_model=BoxSettingsOut)
def get_box_settings(
    _: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> BoxSettingsOut:
    row = service.get_box_settings_row(db)
    return BoxSettingsOut(**service.serialize_settings(row))


@router.put("/settings", response_model=BoxSettingsOut)
def update_box_settings(
    payload: BoxSettingsIn,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> BoxSettingsOut:
    row = service.get_box_settings_row(db)
    before = service.serialize_settings(row)
    try:
        service.apply_settings(row, payload.model_dump(exclude_unset=True), actor_username=actor.username)
    except service.BoxConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    after = service.serialize_settings(row)
    write_audit_log(
        db,
        actor=actor,
        action="update_box_settings",
        target_type="box_settings",
        target_id="global",
        payload_before=before,
        payload_after=after,
        **request_meta(request),
    )
    db.commit()
    db.refresh(row)
    return BoxSettingsOut(**service.serialize_settings(row))


@router.get("/status", response_model=BoxStatusResponse)
def get_box_status(
    _: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> BoxStatusResponse:
    row = service.get_box_settings_row(db)
    return BoxStatusResponse(**service.status(row, user_settings))


@router.post("/oauth/start", response_model=BoxOAuthStartResponse)
def start_box_oauth(
    request: Request,
    payload: BoxOAuthStartRequest | None = None,
    actor: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BoxOAuthStartResponse:
    row = service.get_box_settings_row(db)
    state = secrets.token_urlsafe(32)
    redirect_url = _resolve_redirect_url(request, payload.redirect_uri if payload else None)
    try:
        authorize_url = service.build_authorize_url(row, redirect_uri=redirect_url, state=state)
    except service.BoxConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session_store._client().setex(
        _state_key(state),
        _STATE_TTL_SECONDS,
        json.dumps({"actor_user_id": actor.id, "actor_username": actor.username, "redirect_url": redirect_url}),
    )
    return BoxOAuthStartResponse(authorize_url=authorize_url, redirect_url=redirect_url)


@router.get("/oauth/callback", name="box_oauth_callback")
def box_oauth_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if error:
        return _oauth_html("Box authorization failed", error_description or error, status_code=400)
    if not code or not state:
        return _oauth_html("Box authorization failed", "Missing code or state", status_code=400)
    raw_state = session_store._client().get(_state_key(state))
    if not raw_state:
        return _oauth_html("Box authorization failed", "Authorization session expired", status_code=400)
    session_store._client().delete(_state_key(state))
    state_payload = json.loads(raw_state)
    row = service.get_box_settings_row(db)
    actor_user_id = state_payload.get("actor_user_id")
    if not isinstance(actor_user_id, int):
        return _oauth_html("Box authorization failed", "Authorization session is invalid", status_code=400)
    user_settings = db.get(UserSettings, actor_user_id)
    if not user_settings:
        user_settings = UserSettings(user_id=state_payload.get("actor_user_id"))
        db.add(user_settings)
    try:
        token_payload = service.exchange_code_for_tokens(row, code=code, redirect_uri=state_payload["redirect_url"])
        service.store_tokens(user_settings, token_payload)
    except (service.BoxConfigError, service.BoxClientError) as exc:
        db.rollback()
        return _oauth_html("Box authorization failed", str(exc), status_code=400)
    db.commit()
    return _oauth_html("Box connected", "You can close this tab and return to Contrack.")


@router.post("/upload-access", response_model=BoxUploadAccessResponse)
def get_upload_access(
    _: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> BoxUploadAccessResponse:
    try:
        access_token, row = service.get_valid_access_token(db, user_settings)
    except service.BoxConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except service.BoxClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not row.client_folder_id or not row.server_folder_id:
        raise HTTPException(status_code=400, detail="Box folder ids are incomplete")
    return BoxUploadAccessResponse(
        access_token=access_token,
        expires_at=user_settings.box_token_expires_at,
        client_folder_id=row.client_folder_id,
        server_folder_id=row.server_folder_id,
        shared_link_access=row.shared_link_access or "company",
    )


def _oauth_html(title: str, message: str, *, status_code: int = 200) -> HTMLResponse:
    safe_title = title.replace("<", "&lt;").replace(">", "&gt;")
    safe_message = message.replace("<", "&lt;").replace(">", "&gt;")
    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang="en">
          <head><meta charset="utf-8"><title>{safe_title}</title></head>
          <body style="font-family: system-ui, sans-serif; padding: 32px;">
            <h1>{safe_title}</h1>
            <p>{safe_message}</p>
          </body>
        </html>
        """.strip(),
        status_code=status_code,
    )
