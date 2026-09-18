from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret
from app.models import BoxIntegrationSetting, UserSettings

BOX_AUTHORIZE_URL = "https://account.box.com/api/oauth2/authorize"
BOX_TOKEN_URL = "https://api.box.com/oauth2/token"
BOX_API_BASE = "https://api.box.com/2.0"
_TOKEN_REFRESH_MARGIN = timedelta(minutes=2)
_FOLDER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_SHARED_LINK_ACCESS = {"open", "company", "collaborators"}


class BoxConfigError(ValueError):
    pass


class BoxClientError(RuntimeError):
    pass


class BoxAuthError(BoxClientError):
    """The stored authorization cannot be used and OAuth is required again."""


def get_box_settings_row(db: Session) -> BoxIntegrationSetting:
    row = db.get(BoxIntegrationSetting, 1)
    if row:
        return row
    row = BoxIntegrationSetting(id=1, shared_link_access="company")
    db.add(row)
    db.flush()
    return row


def normalize_optional_text(value: object, *, max_length: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if max_length is not None:
        text = text[:max_length]
    return text or None


def normalize_folder_id(value: object, key: str) -> str | None:
    text = normalize_optional_text(value, max_length=100)
    if text is None:
        return None
    if not _FOLDER_ID_RE.fullmatch(text):
        raise BoxConfigError(f"{key} must be a Box folder id")
    return text


def normalize_shared_link_access(value: object) -> str:
    text = normalize_optional_text(value, max_length=20) or "company"
    if text not in _SHARED_LINK_ACCESS:
        raise BoxConfigError("shared_link_access must be open, company, or collaborators")
    return text


def is_configured(row: BoxIntegrationSetting) -> bool:
    return bool(row.client_id and row.client_secret_enc)


def serialize_settings(row: BoxIntegrationSetting) -> dict:
    return {
        "client_id": row.client_id,
        "client_secret_configured": bool(row.client_secret_enc),
        "shared_link_access": row.shared_link_access or "company",
        "updated_by": row.updated_by,
    }


def status(db: Session, user_settings: UserSettings, *, force_refresh: bool = False) -> dict:
    row = get_box_settings_row(db)
    configured = is_configured(row)
    connected = False
    authorization_required = False
    message = "Box settings are incomplete"
    if configured:
        try:
            _, _, message = get_verified_access_token(db, user_settings, force_refresh=force_refresh)
            connected = True
        except BoxAuthError as exc:
            authorization_required = True
            message = str(exc)
        except (BoxConfigError, BoxClientError) as exc:
            message = str(exc)
    return {
        "configured": configured,
        "connected": connected,
        "authorization_required": authorization_required,
        "message": message,
        "token_expires_at": user_settings.box_token_expires_at,
    }


def apply_settings(row: BoxIntegrationSetting, values: dict[str, object], *, actor_username: str) -> None:
    if "client_id" in values:
        row.client_id = normalize_optional_text(values["client_id"])
    if "client_secret" in values:
        client_secret = normalize_optional_text(values["client_secret"])
        row.client_secret_enc = encrypt_secret(client_secret)
    if "shared_link_access" in values:
        row.shared_link_access = normalize_shared_link_access(values["shared_link_access"])
    row.updated_by = actor_username


def build_authorize_url(row: BoxIntegrationSetting, *, redirect_uri: str, state: str) -> str:
    if not row.client_id:
        raise BoxConfigError("Box client_id is required")
    query = urlencode(
        {
            "response_type": "code",
            "client_id": row.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{BOX_AUTHORIZE_URL}?{query}"


def exchange_code_for_tokens(row: BoxIntegrationSetting, *, code: str, redirect_uri: str) -> dict:
    client_secret = decrypt_secret(row.client_secret_enc)
    if not row.client_id or not client_secret:
        raise BoxConfigError("Box client_id and client_secret are required")
    return _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": row.client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
    )


def refresh_tokens(row: BoxIntegrationSetting, user_settings: UserSettings) -> dict:
    client_secret = decrypt_secret(row.client_secret_enc)
    refresh_token = decrypt_secret(user_settings.box_refresh_token_enc)
    if not row.client_id or not client_secret:
        raise BoxConfigError("Box settings are incomplete")
    if not refresh_token:
        raise BoxAuthError("Box refresh token is not available. Please reconnect to Box.")
    return _token_request(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": row.client_id,
            "client_secret": client_secret,
        }
    )


def _token_request(data: dict[str, str]) -> dict:
    try:
        response = httpx.post(BOX_TOKEN_URL, data=data, timeout=20)
    except httpx.HTTPError as exc:
        raise BoxClientError(f"Box token request failed: {exc}") from exc
    payload = _response_json(response)
    if response.status_code >= 400:
        if payload.get("error") == "invalid_grant":
            raise BoxAuthError("Box authorization expired or was revoked. Please reconnect to Box.")
        if payload.get("error") in {"invalid_client", "unauthorized_client"}:
            raise BoxConfigError("Box client credentials are invalid; ask an administrator to check Box settings")
        raise BoxClientError(_box_error_message(payload, "Box token request failed"))
    return payload


def store_tokens(user_settings: UserSettings, token_payload: dict) -> None:
    access_token = token_payload.get("access_token")
    refresh_token = token_payload.get("refresh_token")
    if not isinstance(access_token, str) or not access_token.strip() or not isinstance(refresh_token, str) or not refresh_token.strip():
        raise BoxClientError("Box token response did not include access_token and refresh_token")
    expires_in = token_payload.get("expires_in")
    expires_seconds = int(expires_in) if isinstance(expires_in, int | float | str) and str(expires_in).isdigit() else 3600
    user_settings.box_access_token_enc = encrypt_secret(access_token)
    user_settings.box_refresh_token_enc = encrypt_secret(refresh_token)
    user_settings.box_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_seconds)


def clear_tokens(user_settings: UserSettings) -> None:
    user_settings.box_access_token_enc = None
    user_settings.box_refresh_token_enc = None
    user_settings.box_token_expires_at = None


def get_valid_access_token(
    db: Session, user_settings: UserSettings, *, force_refresh: bool = False, rejected_token: str | None = None
) -> tuple[str, BoxIntegrationSetting]:
    row = get_box_settings_row(db)
    if not is_configured(row):
        raise BoxConfigError("Box settings are incomplete")
    # Box rotates refresh tokens. Reload under a database lock so concurrent
    # status checks and client/server uploads never reuse an old refresh token.
    db.refresh(user_settings, with_for_update=True)
    try:
        expires_at = _aware(user_settings.box_token_expires_at)
        token = decrypt_secret(user_settings.box_access_token_enc)
        if rejected_token and token and token != rejected_token:
            force_refresh = False  # Another request has already renewed it.
        if token and not force_refresh and expires_at and expires_at > datetime.now(timezone.utc) + _TOKEN_REFRESH_MARGIN:
            db.commit()
            return token, row
        if not user_settings.box_refresh_token_enc:
            raise BoxAuthError("Box authorization is required. Please reconnect to Box.")
        token_payload = refresh_tokens(row, user_settings)
        store_tokens(user_settings, token_payload)
        token = decrypt_secret(user_settings.box_access_token_enc)
        db.commit()
        return token, row
    except BoxAuthError:
        clear_tokens(user_settings)
        db.commit()
        raise
    except Exception:
        db.rollback()
        raise


def _current_user(access_token: str) -> httpx.Response:
    try:
        return httpx.get(
            f"{BOX_API_BASE}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
    except httpx.HTTPError as exc:
        raise BoxClientError(f"Box connection failed: {exc}") from exc


def get_verified_access_token(
    db: Session, user_settings: UserSettings, *, force_refresh: bool = False
) -> tuple[str, BoxIntegrationSetting, str]:
    access_token, row = get_valid_access_token(db, user_settings, force_refresh=force_refresh)
    response = _current_user(access_token)
    if response.status_code == 401:
        access_token, row = get_valid_access_token(db, user_settings, force_refresh=True, rejected_token=access_token)
        response = _current_user(access_token)
    if response.status_code == 401:
        db.refresh(user_settings, with_for_update=True)
        # Do not erase credentials saved by a concurrent OAuth callback.
        if decrypt_secret(user_settings.box_access_token_enc) == access_token:
            clear_tokens(user_settings)
        db.commit()
        raise BoxAuthError("Box authorization is no longer valid. Please reconnect to Box.")
    payload = _response_json(response)
    if response.status_code >= 400:
        raise BoxClientError(_box_error_message(payload, "Box connection failed"))
    if not payload.get("id"):
        raise BoxClientError("Box did not return a valid account; connection could not be verified")
    login = payload.get("login") if isinstance(payload, dict) else None
    return access_token, row, f"Connected to Box{f' as {login}' if login else ''}"


def test_connection(db: Session, user_settings: UserSettings) -> str:
    _, _, message = get_verified_access_token(db, user_settings)
    return message


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _response_json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        return {"message": response.text}
    return data if isinstance(data, dict) else {"message": str(data)}


def _box_error_message(payload: dict, fallback: str) -> str:
    for key in ("error_description", "message", "error"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback
