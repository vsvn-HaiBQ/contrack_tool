import re

from sqlalchemy.orm import Session
from urllib.parse import urlparse

from app.core.security import decrypt_secret, encrypt_secret, hash_password
from app.models import User, UserSettings
from app.schemas import DocumentTranslationSettingsOut, UserSettingsOut

_UNSET = object()


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
        team_automate_url=decrypt_secret(settings.team_automate_url_enc),
        default_assignee_id=settings.default_assignee_id,
        document_translation=serialize_document_translation_settings(settings),
    )


def serialize_document_translation_settings(settings: UserSettings) -> DocumentTranslationSettingsOut:
    return DocumentTranslationSettingsOut(
        output_directory=settings.document_translation_output_directory,
        direction=settings.document_translation_direction,
        model=settings.document_translation_model,
        reasoning_effort=settings.document_translation_reasoning_effort,
        timeout_seconds=settings.document_translation_timeout_seconds,
        batch_size=settings.document_translation_batch_size,
        context_window=settings.document_translation_context_window,
        fast_mode=settings.document_translation_fast_mode,
        glossary=settings.document_translation_glossary,
        instructions=settings.document_translation_instructions,
    )


def apply_user_settings(
    settings: UserSettings,
    *,
    redmine_jp_api_key: object = _UNSET,
    redmine_vn_api_key: object = _UNSET,
    github_token: object = _UNSET,
    team_automate_url: object = _UNSET,
    default_assignee_id: object = _UNSET,
) -> None:
    if redmine_jp_api_key is not _UNSET:
        settings.redmine_jp_api_key_enc = encrypt_secret(redmine_jp_api_key if isinstance(redmine_jp_api_key, str) else None)
    if redmine_vn_api_key is not _UNSET:
        settings.redmine_vn_api_key_enc = encrypt_secret(redmine_vn_api_key if isinstance(redmine_vn_api_key, str) else None)
    if github_token is not _UNSET:
        settings.github_token_enc = encrypt_secret(github_token if isinstance(github_token, str) else None)
    if team_automate_url is not _UNSET:
        settings.team_automate_url_enc = encrypt_secret(team_automate_url if isinstance(team_automate_url, str) else None)
    if default_assignee_id is not _UNSET:
        settings.default_assignee_id = default_assignee_id if isinstance(default_assignee_id, int) else None


def serialize_local_paths(settings: UserSettings) -> dict[str, str | None]:
    return {
        "build_source_folder": settings.build_source_folder,
        "build_output_folder": settings.build_output_folder,
        "git_eol_source_folder": settings.git_eol_source_folder,
    }


def normalize_local_path(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def apply_local_paths(
    settings: UserSettings,
    *,
    build_source_folder: object = _UNSET,
    build_output_folder: object = _UNSET,
    git_eol_source_folder: object = _UNSET,
) -> None:
    if build_source_folder is not _UNSET:
        settings.build_source_folder = normalize_local_path(build_source_folder if isinstance(build_source_folder, str) else None)
    if build_output_folder is not _UNSET:
        settings.build_output_folder = normalize_local_path(build_output_folder if isinstance(build_output_folder, str) else None)
    if git_eol_source_folder is not _UNSET:
        settings.git_eol_source_folder = normalize_local_path(git_eol_source_folder if isinstance(git_eol_source_folder, str) else None)


def _normalize_optional_text(value: object, max_length: int | None = None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if max_length is not None:
        text = text[:max_length]
    return text or None


def _normalize_optional_int(value: object, *, min_value: int, max_value: int) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError("translation numeric settings must be integers")
    if value < min_value or value > max_value:
        raise ValueError(f"translation numeric settings must be between {min_value} and {max_value}")
    return value


def apply_document_translation_settings(settings: UserSettings, **values: object) -> None:
    if "output_directory" in values:
        settings.document_translation_output_directory = normalize_local_path(
            values["output_directory"] if isinstance(values["output_directory"], str) else None
        )
    if "direction" in values:
        direction = _normalize_optional_text(values["direction"], 20)
        if direction is not None and direction not in {"ja_to_vi", "vi_to_ja"}:
            raise ValueError("document translation direction must be ja_to_vi or vi_to_ja")
        settings.document_translation_direction = direction
    if "model" in values:
        settings.document_translation_model = _normalize_optional_text(values["model"], 100)
    if "reasoning_effort" in values:
        reasoning_effort = _normalize_optional_text(values["reasoning_effort"], 20)
        if reasoning_effort is not None and reasoning_effort not in {"low", "medium", "high", "xhigh"}:
            raise ValueError("document translation reasoning_effort must be low, medium, high, or xhigh")
        settings.document_translation_reasoning_effort = reasoning_effort
    if "timeout_seconds" in values:
        settings.document_translation_timeout_seconds = _normalize_optional_int(values["timeout_seconds"], min_value=5, max_value=3600)
    if "batch_size" in values:
        settings.document_translation_batch_size = _normalize_optional_int(values["batch_size"], min_value=1, max_value=200)
    if "context_window" in values:
        settings.document_translation_context_window = _normalize_optional_int(values["context_window"], min_value=0, max_value=200)
    if "fast_mode" in values:
        fast_mode = values["fast_mode"]
        settings.document_translation_fast_mode = fast_mode if isinstance(fast_mode, bool) else None
    if "glossary" in values:
        settings.document_translation_glossary = values["glossary"] if isinstance(values["glossary"], str) and values["glossary"].strip() else None
    if "instructions" in values:
        settings.document_translation_instructions = values["instructions"] if isinstance(values["instructions"], str) and values["instructions"].strip() else None


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
    redmine_jp_api_key: object = _UNSET,
    redmine_vn_api_key: object = _UNSET,
    github_token: object = _UNSET,
    team_automate_url: object = _UNSET,
    default_assignee_id: object = _UNSET,
) -> dict[str, str | int | None | object]:
    if (
        default_assignee_id is not _UNSET
        and default_assignee_id is not None
        and (not isinstance(default_assignee_id, int) or default_assignee_id <= 0)
    ):
        raise ValueError("default_assignee_id must be a positive integer")
    validated: dict[str, str | int | None | object] = {}
    if redmine_jp_api_key is not _UNSET:
        validated["redmine_jp_api_key"] = redmine_jp_api_key.strip() if isinstance(redmine_jp_api_key, str) and redmine_jp_api_key.strip() else None
    if redmine_vn_api_key is not _UNSET:
        validated["redmine_vn_api_key"] = redmine_vn_api_key.strip() if isinstance(redmine_vn_api_key, str) and redmine_vn_api_key.strip() else None
    if github_token is not _UNSET:
        validated["github_token"] = github_token.strip() if isinstance(github_token, str) and github_token.strip() else None
    if team_automate_url is not _UNSET:
        value = team_automate_url.strip() if isinstance(team_automate_url, str) and team_automate_url.strip() else None
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("team_automate_url must be a valid http or https URL")
        validated["team_automate_url"] = value
    if default_assignee_id is not _UNSET:
        validated["default_assignee_id"] = default_assignee_id
    return validated
