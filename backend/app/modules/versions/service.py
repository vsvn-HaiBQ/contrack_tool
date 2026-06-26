from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import UserSettings, Version

_NAME_RE = re.compile(r"^[A-Za-z0-9 _.\-/]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]{1,200}$")
_FOLDER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,100}$")


class VersionValidationError(ValueError):
    pass


def _normalize_text(value: object, *, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if max_length:
        text = text[:max_length]
    return text or None


def _validate_name(value: object) -> str:
    text = _normalize_text(value, max_length=100)
    if not text:
        raise VersionValidationError("name is required")
    if not _NAME_RE.fullmatch(text):
        raise VersionValidationError("name contains invalid characters")
    return text


def _validate_branch(value: object) -> str | None:
    text = _normalize_text(value, max_length=200)
    if text is None:
        return None
    if not _BRANCH_RE.fullmatch(text):
        raise VersionValidationError("default_base_branch contains invalid characters")
    return text


def _validate_folder_id(value: object, key: str) -> str | None:
    text = _normalize_text(value, max_length=100)
    if text is None:
        return None
    if not _FOLDER_ID_RE.fullmatch(text):
        raise VersionValidationError(f"{key} must be a Box folder id")
    return text


def serialize(row: Version) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "default_base_branch": row.default_base_branch,
        "client_folder_id": row.client_folder_id,
        "server_folder_id": row.server_folder_id,
        "client_baseline_folder": row.client_baseline_folder,
        "server_baseline_folder": row.server_baseline_folder,
        "position": row.position,
        "updated_by": row.updated_by,
    }


def list_versions(db: Session) -> list[Version]:
    return db.query(Version).order_by(Version.position.asc(), Version.id.asc()).all()


def get_version(db: Session, version_id: int) -> Version | None:
    return db.get(Version, version_id)


def _next_position(db: Session) -> int:
    rows = db.query(Version.position).all()
    return (max((row[0] for row in rows), default=-1)) + 1


def apply_payload(row: Version, values: dict, *, actor_username: str | None) -> None:
    if "name" in values:
        row.name = _validate_name(values["name"])
    if "default_base_branch" in values:
        row.default_base_branch = _validate_branch(values["default_base_branch"])
    if "client_folder_id" in values:
        row.client_folder_id = _validate_folder_id(values["client_folder_id"], "client_folder_id")
    if "server_folder_id" in values:
        row.server_folder_id = _validate_folder_id(values["server_folder_id"], "server_folder_id")
    if "client_baseline_folder" in values:
        row.client_baseline_folder = _validate_folder_id(values["client_baseline_folder"], "client_baseline_folder")
    if "server_baseline_folder" in values:
        row.server_baseline_folder = _validate_folder_id(values["server_baseline_folder"], "server_baseline_folder")
    if "position" in values and isinstance(values["position"], int):
        row.position = max(0, values["position"])
    if actor_username:
        row.updated_by = actor_username


def create_version(db: Session, values: dict, *, actor_username: str) -> Version:
    if "name" not in values:
        raise VersionValidationError("name is required")
    name = _validate_name(values["name"])
    if db.query(Version).filter(Version.name == name).first():
        raise VersionValidationError("A version with this name already exists")
    row = Version(name=name, position=_next_position(db))
    apply_payload(row, {**values, "name": name}, actor_username=actor_username)
    db.add(row)
    db.flush()
    return row


def update_version(db: Session, row: Version, values: dict, *, actor_username: str) -> Version:
    if "name" in values:
        new_name = _validate_name(values["name"])
        if new_name != row.name and db.query(Version).filter(Version.name == new_name, Version.id != row.id).first():
            raise VersionValidationError("A version with this name already exists")
    apply_payload(row, values, actor_username=actor_username)
    db.flush()
    return row


def delete_version(db: Session, row: Version) -> None:
    db.query(UserSettings).filter(UserSettings.pinned_version_id == row.id).update(
        {UserSettings.pinned_version_id: None}, synchronize_session=False
    )
    db.delete(row)


def pin_version(db: Session, user_id: int, version_id: int | None) -> UserSettings:
    settings = db.get(UserSettings, user_id)
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.add(settings)
    if version_id is not None:
        if not db.get(Version, version_id):
            raise VersionValidationError("Version not found")
    settings.pinned_version_id = version_id
    db.flush()
    return settings


def get_pinned_version(db: Session, user_settings: UserSettings | None) -> Version | None:
    if not user_settings or not user_settings.pinned_version_id:
        return None
    return db.get(Version, user_settings.pinned_version_id)
