import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

from app.core.config import settings

TOKEN_TTL_SECONDS = 10 * 60


class ReleaseNotFoundError(Exception):
    pass


class InvalidDownloadTokenError(Exception):
    pass


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def release_directory() -> Path:
    candidates: list[Path] = []
    if settings.local_server_release_dir.strip():
        candidates.append(Path(settings.local_server_release_dir))
    candidates.extend(
        [
            _repo_root() / "build_output" / "releases" / "local-server",
            Path("/app/local_server_releases"),
        ]
    )
    for candidate in candidates:
        if (candidate / "latest.json").is_file():
            return candidate
    return candidates[0]


def _safe_package_path(base_dir: Path, file_name: str) -> Path:
    if not file_name or "/" in file_name or "\\" in file_name:
        raise ReleaseNotFoundError("Release package file is invalid")
    package_path = (base_dir / file_name).resolve()
    base_path = base_dir.resolve()
    if package_path.parent != base_path:
        raise ReleaseNotFoundError("Release package file is invalid")
    if not package_path.is_file():
        raise ReleaseNotFoundError("Release package file not found")
    return package_path


def latest_release_manifest() -> dict[str, Any]:
    base_dir = release_directory()
    manifest_path = base_dir / "latest.json"
    if not manifest_path.is_file():
        raise ReleaseNotFoundError("Local server release manifest not found")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseNotFoundError(f"Local server release manifest is invalid: {exc}") from exc
    package_path = _safe_package_path(base_dir, str(manifest.get("package_file") or ""))
    manifest["package_size_bytes"] = package_path.stat().st_size
    if manifest.get("zip_file"):
        zip_path = _safe_package_path(base_dir, str(manifest.get("zip_file") or ""))
        manifest["zip_size_bytes"] = zip_path.stat().st_size
    api_prefix = settings.api_prefix.rstrip("/")
    manifest["download_url"] = f"{api_prefix}/local-server/releases/{manifest.get('version')}/download"
    manifest["zip_download_url"] = f"{api_prefix}/local-server/releases/{manifest.get('version')}/download-zip"
    return manifest


def package_path_for_version(version: str) -> Path:
    manifest = latest_release_manifest()
    if version != manifest.get("version"):
        raise ReleaseNotFoundError("Requested local server release version is not available")
    return _safe_package_path(release_directory(), str(manifest.get("package_file") or ""))


def zip_path_for_version(version: str) -> Path:
    manifest = latest_release_manifest()
    if version != manifest.get("version"):
        raise ReleaseNotFoundError("Requested local server release version is not available")
    return _safe_package_path(release_directory(), str(manifest.get("zip_file") or ""))


def _signing_key() -> bytes:
    return hashlib.sha256(settings.master_key.encode("utf-8")).digest()


def _token_signature(version: str, expires_at: int) -> str:
    payload = f"{version}:{expires_at}".encode("utf-8")
    return hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()


def create_download_token(version: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> tuple[str, int]:
    expires_at = int(time.time()) + ttl_seconds
    signature = _token_signature(version, expires_at)
    raw = f"{version}:{expires_at}:{signature}".encode("utf-8")
    token = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    return token, expires_at


def validate_download_token(version: str, token: str) -> None:
    if not token:
        raise InvalidDownloadTokenError("Download token is required")
    padded = token + "=" * (-len(token) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        token_version, raw_expires_at, signature = decoded.split(":", 2)
        expires_at = int(raw_expires_at)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidDownloadTokenError("Download token is invalid") from exc
    if token_version != version:
        raise InvalidDownloadTokenError("Download token version does not match")
    if expires_at < int(time.time()):
        raise InvalidDownloadTokenError("Download token expired")
    expected = _token_signature(version, expires_at)
    if not hmac.compare_digest(signature, expected):
        raise InvalidDownloadTokenError("Download token signature is invalid")
