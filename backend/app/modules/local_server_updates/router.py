from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import settings
from app.dependencies import get_current_user
from app.models import User
from app.modules.local_server_updates.service import (
    InvalidDownloadTokenError,
    ReleaseNotFoundError,
    create_download_token,
    latest_release_manifest,
    package_path_for_version,
    validate_download_token,
    zip_path_for_version,
)

router = APIRouter(prefix="/local-server/releases", tags=["local-server"])


@router.get("/latest")
def get_latest_release(_: User = Depends(get_current_user)) -> dict:
    try:
        return latest_release_manifest()
    except ReleaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{version}/download-ticket")
def create_release_download_ticket(version: str, _: User = Depends(get_current_user)) -> dict:
    try:
        manifest = latest_release_manifest()
    except ReleaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if version != manifest.get("version"):
        raise HTTPException(status_code=404, detail="Requested local server release version is not available")
    token, expires_at = create_download_token(version)
    api_prefix = settings.api_prefix.rstrip("/")
    return {
        "version": version,
        "download_url": f"{api_prefix}/local-server/releases/{version}/download?token={token}",
        "zip_download_url": f"{api_prefix}/local-server/releases/{version}/download-zip?token={token}",
        "expires_at": expires_at,
    }


@router.get("/{version}/download")
def download_release(version: str, token: str = Query(default="")) -> FileResponse:
    try:
        validate_download_token(version, token)
        package_path = package_path_for_version(version)
    except InvalidDownloadTokenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReleaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        package_path,
        media_type="application/gzip",
        filename=package_path.name,
    )


@router.get("/{version}/download-zip")
def download_release_zip(version: str, token: str = Query(default="")) -> FileResponse:
    try:
        validate_download_token(version, token)
        package_path = zip_path_for_version(version)
    except InvalidDownloadTokenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ReleaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        package_path,
        media_type="application/zip",
        filename=package_path.name,
    )
