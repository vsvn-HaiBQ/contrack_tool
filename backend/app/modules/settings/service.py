import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import SystemSetting

SYSTEM_SETTING_KEYS = [
    "git_repo",
    "redmine_jp_host",
    "redmine_vn_host",
    "redmine_vn_project_id",
    "default_base_branch",
    "description_template",
]


def ensure_system_settings(db: Session) -> None:
    for key in SYSTEM_SETTING_KEYS:
        if not db.get(SystemSetting, key):
            db.add(SystemSetting(key=key, value=None))
    db.commit()


def get_system_settings_map(db: Session) -> dict[str, str | None]:
    ensure_system_settings(db)
    rows = db.query(SystemSetting).all()
    row_map = {row.key: row.value for row in rows}
    return {key: row_map.get(key) for key in SYSTEM_SETTING_KEYS}


def _validate_url(value: str, key: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{key} must be a valid http/https URL")


def _validate_positive_int(value: str, key: str) -> None:
    if not value.isdigit() or int(value) <= 0:
        raise ValueError(f"{key} must be a positive integer")


def validate_system_settings(values: dict[str, str | None]) -> dict[str, str | None]:
    validated: dict[str, str | None] = {}
    for key, raw_value in values.items():
        if key not in SYSTEM_SETTING_KEYS:
            continue
        value = raw_value.strip() if isinstance(raw_value, str) else raw_value
        if value == "":
            value = None
        if value is None:
            validated[key] = None
            continue
        if key in {"redmine_jp_host", "redmine_vn_host"}:
            _validate_url(value, key)
        elif key == "git_repo":
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
                raise ValueError("git_repo must use owner/repo format")
        elif key == "redmine_vn_project_id":
            _validate_positive_int(value, key)
        elif key == "default_base_branch":
            if not re.fullmatch(r"[A-Za-z0-9._/-]+", value):
                raise ValueError("default_base_branch contains invalid characters")
        validated[key] = value
    return validated
