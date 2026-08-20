from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.dependencies import require_menu_permission
from app.models import User
from app.modules.confluence_preview.service import convert_content

router = APIRouter(prefix="/confluence-preview", tags=["confluence-preview"])

MAX_CONFLUENCE_BYTES = 10 * 1024 * 1024


class ConfluencePreviewOut(BaseModel):
    file_name: str
    title: str
    html: str


@router.post("", response_model=ConfluencePreviewOut)
async def preview_confluence(
    file: UploadFile = File(...),
    assets_dir: str | None = Form(default=None),
    _: User = Depends(require_menu_permission("confluence_preview")),
) -> ConfluencePreviewOut:
    file_name = file.filename or "page.confluence"
    if not file_name.lower().endswith(".confluence"):
        raise HTTPException(status_code=400, detail="Only .confluence files are supported")

    content = await file.read(MAX_CONFLUENCE_BYTES + 1)
    if len(content) > MAX_CONFLUENCE_BYTES:
        raise HTTPException(status_code=413, detail="Confluence file is too large")

    title, document = convert_content(content, assets_dir=assets_dir)
    return ConfluencePreviewOut(file_name=file_name, title=title, html=document)
