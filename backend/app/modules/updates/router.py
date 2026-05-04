from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.core.config import settings
from app.schemas import ClientUpdateResponse

router = APIRouter(tags=["updates"])

ARTIFACT_PATTERN = re.compile(r"Contrack-Client-(?P<version>.+)-portable\.(?:exe|zip)$", re.IGNORECASE)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _release_dir() -> Path:
    configured = Path(settings.release_dir)
    if configured.is_absolute():
        return configured
    return (_repo_root() / configured).resolve()


def _safe_file_name(file_name: str) -> str:
    if not file_name or Path(file_name).name != file_name:
        raise HTTPException(status_code=400, detail="Invalid file name")
    return file_name


def _version_key(version: str) -> tuple:
    parts: list[tuple[int, int | str]] = []
    for token in re.split(r"([0-9]+)", version):
        if not token:
            continue
        parts.append((0, int(token)) if token.isdigit() else (1, token.lower()))
    return tuple(parts)


def _candidate_artifacts() -> list[dict]:
    release_dir = _release_dir()
    if not release_dir.is_dir():
        return []
    artifacts = []
    for path in release_dir.iterdir():
        if not path.is_file():
            continue
        match = ARTIFACT_PATTERN.match(path.name)
        if not match:
            continue
        stat = path.stat()
        artifacts.append(
            {
                "path": path,
                "file_name": path.name,
                "version": match.group("version"),
                "size_bytes": stat.st_size,
                "published_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            }
        )
    artifacts.sort(key=lambda item: (_version_key(item["version"]), item["published_at"]), reverse=True)
    return artifacts


def _is_newer(latest: str | None, current: str | None) -> bool:
    if not latest:
        return False
    if not current:
        return True
    return _version_key(latest) > _version_key(current)


@router.get("/checkupdate", response_model=ClientUpdateResponse)
def check_update(
    request: Request,
    current_version: str | None = Query(default=None),
) -> ClientUpdateResponse:
    artifacts = _candidate_artifacts()
    if not artifacts:
        return ClientUpdateResponse(
            current_version=current_version,
            has_update=False,
            message=f"Chưa có bản release trong {_release_dir()}",
        )
    latest = artifacts[0]
    download_url = str(request.url_for("download_client_update", file_name=latest["file_name"]))
    latest_version = latest["version"]
    has_update = _is_newer(latest_version, current_version)
    return ClientUpdateResponse(
        current_version=current_version,
        latest_version=latest_version,
        has_update=has_update,
        file_name=latest["file_name"],
        download_url=download_url,
        size_bytes=latest["size_bytes"],
        published_at=latest["published_at"],
        message="Có phiên bản mới" if has_update else "Client đang ở phiên bản mới nhất",
    )


@router.get("/checkupdate/download/{file_name}", name="download_client_update")
def download_client_update(file_name: str) -> FileResponse:
    safe_name = _safe_file_name(file_name)
    target = (_release_dir() / safe_name).resolve()
    try:
        target.relative_to(_release_dir())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file name") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Release file not found")
    return FileResponse(target, filename=target.name, media_type="application/octet-stream")
