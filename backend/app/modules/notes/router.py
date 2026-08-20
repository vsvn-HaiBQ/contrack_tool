from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_admin_user, get_current_user, require_menu_permission, request_meta
from app.models import Note, User
from app.modules.audit.service import write_audit_log
from app.schemas import NoteCreateRequest, NoteOut, NoteReorderRequest, NoteUpdateRequest

router = APIRouter(prefix="/notes", tags=["notes"], dependencies=[Depends(require_menu_permission("notes"))])


@router.get("", response_model=list[NoteOut])
def list_notes(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[NoteOut]:
    return db.query(Note).order_by(Note.position.asc(), Note.created_at.asc()).all()


@router.post("", response_model=NoteOut, status_code=201)
def create_note(
    payload: NoteCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteOut:
    max_pos = db.query(Note).count()
    note = Note(
        title=payload.title.strip(),
        content=payload.content,
        created_by=user.username,
        position=max_pos,
    )
    db.add(note)
    db.flush()
    write_audit_log(
        db,
        actor=user,
        action="create_note",
        target_type="note",
        target_id=str(note.id),
        payload_after={"title": note.title, "content": note.content},
        **request_meta(request),
    )
    db.commit()
    db.refresh(note)
    return note


@router.patch("/reorder", response_model=list[NoteOut])
def reorder_notes(
    payload: NoteReorderRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[NoteOut]:
    for position, note_id in enumerate(payload.ids):
        note = db.get(Note, note_id)
        if note:
            note.position = position
    db.commit()
    return db.query(Note).order_by(Note.position.asc(), Note.created_at.asc()).all()


@router.put("/{note_id}", response_model=NoteOut)
def update_note(
    note_id: int,
    payload: NoteUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NoteOut:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.locked and user.role != "admin":
        raise HTTPException(status_code=403, detail="Note is locked")
    payload_before = {"title": note.title, "content": note.content}
    note.title = payload.title.strip()
    note.content = payload.content
    write_audit_log(
        db,
        actor=user,
        action="update_note",
        target_type="note",
        target_id=str(note_id),
        payload_before=payload_before,
        payload_after={"title": note.title, "content": note.content},
        **request_meta(request),
    )
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=204)
def delete_note(
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    if note.locked and user.role != "admin":
        raise HTTPException(status_code=403, detail="Note is locked")
    write_audit_log(
        db,
        actor=user,
        action="delete_note",
        target_type="note",
        target_id=str(note_id),
        payload_before={"title": note.title, "content": note.content},
        **request_meta(request),
    )
    db.delete(note)
    db.commit()


@router.patch("/{note_id}/lock", response_model=NoteOut)
def toggle_lock(
    note_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(get_admin_user),
) -> NoteOut:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    new_locked = not note.locked
    note.locked = new_locked
    write_audit_log(
        db,
        actor=actor,
        action="lock_note" if new_locked else "unlock_note",
        target_type="note",
        target_id=str(note_id),
        payload_after={"title": note.title, "locked": new_locked},
        **request_meta(request),
    )
    db.commit()
    db.refresh(note)
    return note
