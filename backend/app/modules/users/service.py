import re

from sqlalchemy.orm import Session

from app.core.security import decrypt_secret, encrypt_secret, hash_password
from app.models import User, UserSettings
from app.schemas import UserSettingsOut


def create_user_record(db: Session, *, username: str, password: str, role: str) -> User:
    user = User(username=username, password_hash=hash_password(password), role=role)
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id))
    return user


def update_password(user: User, password: str) -> None:
    user.password_hash = hash_password(password)


def serialize_user_settings(settings: UserSettings) -> UserSettingsOut:
    return UserSettingsOut(
        redmine_jp_api_key=decrypt_secret(settings.redmine_jp_api_key_enc),
        redmine_vn_api_key=decrypt_secret(settings.redmine_vn_api_key_enc),
        github_token=decrypt_secret(settings.github_token_enc),
        default_assignee_id=settings.default_assignee_id,
    )


def apply_user_settings(
    settings: UserSettings,
    *,
    redmine_jp_api_key: str | None,
    redmine_vn_api_key: str | None,
    github_token: str | None,
    default_assignee_id: int | None,
) -> None:
    settings.redmine_jp_api_key_enc = encrypt_secret(redmine_jp_api_key)
    settings.redmine_vn_api_key_enc = encrypt_secret(redmine_vn_api_key)
    settings.github_token_enc = encrypt_secret(github_token)
    settings.default_assignee_id = default_assignee_id


def validate_username(username: str) -> str:
    value = username.strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,100}", value):
        raise ValueError("Username must be 3-100 chars and use only letters, numbers, dot, underscore, hyphen")
    return value


def validate_password(password: str) -> str:
    if not password:
        raise ValueError("Password is required")
    return password


def validate_user_settings_input(
    *,
    redmine_jp_api_key: str | None,
    redmine_vn_api_key: str | None,
    github_token: str | None,
    default_assignee_id: int | None,
) -> dict[str, str | int | None]:
    if default_assignee_id is not None and default_assignee_id <= 0:
        raise ValueError("default_assignee_id must be a positive integer")
    return {
        "redmine_jp_api_key": redmine_jp_api_key.strip() if isinstance(redmine_jp_api_key, str) and redmine_jp_api_key.strip() else None,
        "redmine_vn_api_key": redmine_vn_api_key.strip() if isinstance(redmine_vn_api_key, str) and redmine_vn_api_key.strip() else None,
        "github_token": github_token.strip() if isinstance(github_token, str) and github_token.strip() else None,
        "default_assignee_id": default_assignee_id,
    }
