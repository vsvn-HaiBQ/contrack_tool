from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from concurrent.futures import ThreadPoolExecutor
import re
from urllib.parse import urlparse

from app.db import get_db
from app.dependencies import get_admin_user, get_current_user, request_meta
from app.models import ManagedTicket, TicketLink, User, UserManagedTicketFollow, UserSettings
from app.modules.redmine import provider as redmine
from app.modules.tickets.service import ensure_managed_ticket, ensure_ticket_follow, ensure_ticket_follow_schema, remove_ticket_follow
from app.modules.users.dependencies import get_current_user_settings
from app.schemas import (
    ChildIssueCreateRequest,
    ManagedTicketListItem,
    MessageResponse,
    SyncActionResponse,
    SyncIssueSummary,
    SyncActionRequest,
    TicketDetailResponse,
    TicketIssueSummary,
    TicketLinkIn,
    TicketLinkOut,
    TicketStatusAssigneeUpdate,
    VerifySyncRequest,
    VerifySyncResponse,
    VNTicketReference,
)
from app.modules.audit.service import write_audit_log
from app.modules.settings.service import get_system_settings_map

router = APIRouter(prefix="/tickets", tags=["tickets"])


_JP_ISSUE_URL_RE = re.compile(r"/issues/(\d+)")


def _resolve_jp_issue_id(payload_id: int | None, payload_url: str | None) -> int:
    """Accept either an explicit jp_issue_id or a Redmine issue URL/path."""
    if payload_id:
        return payload_id
    if payload_url:
        candidate = payload_url.strip()
        if candidate.isdigit():
            return int(candidate)
        match = _JP_ISSUE_URL_RE.search(candidate)
        if match:
            return int(match.group(1))
    raise HTTPException(status_code=400, detail="jp_issue_id or jp_issue_url is required")


def _derive_link_label(link_type: str, url: str, explicit_label: str | None) -> str:
    if explicit_label and explicit_label.strip():
        return explicit_label.strip()[:255]

    parsed = urlparse(url.strip())
    host = parsed.netloc or "link"
    path = parsed.path.rstrip("/") or "/"
    compact_path = path if len(path) <= 80 else f"{path[:77]}..."
    label = f"{link_type.upper()} | {host}{compact_path}"
    return label[:255]


@router.get("/search")
def search_ticket(jp_issue_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    _ = user
    ticket = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    return {
        "exists": bool(ticket),
        "managed_ticket_id": ticket.id if ticket else None,
        "vn_issue_id": ticket.vn_issue_id if ticket else None,
    }


@router.get("/managed", response_model=list[ManagedTicketListItem])
def list_managed_tickets(
    scope: str = "following",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ManagedTicketListItem]:
    ensure_ticket_follow_schema(db)
    settings = get_system_settings_map(db)
    user_settings = db.get(UserSettings, user.id)
    query = db.query(ManagedTicket)
    if scope == "following":
        query = (
            query.join(UserManagedTicketFollow, UserManagedTicketFollow.managed_ticket_id == ManagedTicket.id)
            .filter(UserManagedTicketFollow.user_id == user.id)
        )
    rows = query.order_by(ManagedTicket.updated_at.desc(), ManagedTicket.id.desc()).all()
    if not rows:
        return []
    followed_ids = {
        managed_ticket_id
        for (managed_ticket_id,) in db.query(UserManagedTicketFollow.managed_ticket_id)
        .filter(UserManagedTicketFollow.user_id == user.id)
        .all()
    }

    vn_host = settings.get("redmine_vn_host")
    jp_host_prefix = settings.get("redmine_jp_host", "").rstrip("/")
    vn_host_prefix = (vn_host or "").rstrip("/")

    def _fetch(row: ManagedTicket) -> ManagedTicketListItem:
        subject = f"VN #{row.vn_issue_id}"
        status = "Unknown"
        assignee = None
        if user_settings:
            try:
                issue = redmine.get_issue_resolved(
                    vn_host,
                    user_settings.redmine_vn_api_key_enc,
                    row.vn_issue_id,
                )
                subject = issue.subject
                status = issue.status
                assignee = issue.assignee
            except (redmine.IntegrationConfigError, redmine.RedmineClientError):
                pass
        return ManagedTicketListItem(
            managed_ticket_id=row.id,
            jp_issue_id=row.jp_issue_id,
            jp_url=f"{jp_host_prefix}/issues/{row.jp_issue_id}",
            vn_issue_id=row.vn_issue_id,
            vn_url=f"{vn_host_prefix}/issues/{row.vn_issue_id}",
            subject=subject,
            status=status,
            assignee=assignee,
            is_following=row.id in followed_ids,
        )

    with ThreadPoolExecutor(max_workers=min(8, len(rows))) as executor:
        return list(executor.map(_fetch, rows))


@router.post("/sync/verify", response_model=VerifySyncResponse)
def verify_sync(
    payload: VerifySyncRequest,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> VerifySyncResponse:
    _ = user
    settings = get_system_settings_map(db)
    jp_issue_id = _resolve_jp_issue_id(payload.jp_issue_id, payload.jp_issue_url)
    try:
        jp_issue = redmine.verify_jp_issue_resolved(jp_issue_id, settings.get("redmine_jp_host"), user_settings.redmine_jp_api_key_enc)
        candidates = redmine.search_reference_tickets_resolved(
            settings.get("redmine_vn_host"),
            user_settings.redmine_vn_api_key_enc,
            settings.get("redmine_vn_project_id"),
            jp_issue_id,
        )
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VerifySyncResponse(
        jp_issue_id=jp_issue_id,
        jp_subject=jp_issue.subject,
        jp_issue_url=jp_issue.url,
        candidates=[
            VNTicketReference(
                issue_id=item.issue_id,
                subject=item.subject,
                assignee=item.assignee,
                tracker=item.tracker,
                status=item.status,
                url=item.url,
                parent_issue_id=item.parent_issue_id,
            )
            for item in candidates
        ],
    )


@router.post("/sync", response_model=SyncActionResponse)
def sync_ticket(
    payload: SyncActionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> MessageResponse:
    jp_issue_id = payload.jp_issue_id
    ticket = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    settings = get_system_settings_map(db)
    if payload.mode == "link":
        if not payload.existing_vn_issue_id:
            raise HTTPException(status_code=400, detail="existing_vn_issue_id is required for link mode")
        try:
            existing_issue = redmine.get_issue_resolved(
                settings.get("redmine_vn_host"),
                user_settings.redmine_vn_api_key_enc,
                payload.existing_vn_issue_id,
            )
        except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if existing_issue.tracker.strip().lower() != "story":
            raise HTTPException(status_code=400, detail="Only Story tickets can be linked as the main VN issue")
        if not ticket:
            ticket = ManagedTicket(jp_issue_id=jp_issue_id, vn_issue_id=payload.existing_vn_issue_id, created_by=user.username)
            db.add(ticket)
            db.flush()
        else:
            ticket.vn_issue_id = payload.existing_vn_issue_id
        ensure_ticket_follow(db, user_id=user.id, managed_ticket_id=ticket.id)
        story_summary = SyncIssueSummary(
            issue_id=payload.existing_vn_issue_id,
            subject=existing_issue.subject,
            tracker=existing_issue.tracker,
            url=existing_issue.url,
        )
        subtasks: list[SyncIssueSummary] = []
    else:
        try:
            jp_issue = redmine.verify_jp_issue_resolved(jp_issue_id, settings.get("redmine_jp_host"), user_settings.redmine_jp_api_key_enc)
            candidates = redmine.search_reference_tickets_resolved(
                settings.get("redmine_vn_host"),
                user_settings.redmine_vn_api_key_enc,
                settings.get("redmine_vn_project_id"),
                jp_issue_id,
            )
            if candidates and not payload.force_create:
                raise HTTPException(
                    status_code=400,
                    detail="VN reference tickets already exist. Link an existing Story or force create to continue.",
                )
            sync_result = redmine.create_vn_ticket_resolved(
                vn_host=settings.get("redmine_vn_host"),
                vn_api_key_enc=user_settings.redmine_vn_api_key_enc,
                project_id=settings.get("redmine_vn_project_id"),
                jp_issue_id=jp_issue_id,
                jp_issue_url=f"{settings.get('redmine_jp_host', '').rstrip('/')}/issues/{jp_issue_id}",
                jp_subject=jp_issue.subject,
                subject=payload.subject,
                description=payload.description,
                assignee_id=payload.assignee_id,
                parent_issue_id=payload.parent_issue_id,
                related_ticket_id=payload.related_ticket_id,
                create_subtasks=payload.create_subtasks,
                description_template=settings.get("description_template"),
                main_tracker=payload.extra_tracker,
            )
        except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        story = sync_result["story"]
        created_subtasks = sync_result["subtasks"]
        ticket = ensure_managed_ticket(db, jp_issue_id=jp_issue_id, vn_issue_id=story.issue_id, actor_username=user.username)
        ensure_ticket_follow(db, user_id=user.id, managed_ticket_id=ticket.id)
        story_summary = SyncIssueSummary(issue_id=story.issue_id, subject=story.subject, tracker=story.tracker, url=story.url)
        subtasks = [SyncIssueSummary(issue_id=item.issue_id, subject=item.subject, tracker=item.tracker, url=item.url) for item in created_subtasks]
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="sync_ticket",
        target_type="managed_ticket",
        target_id=str(jp_issue_id),
        payload_after=payload.model_dump(),
        **meta,
    )
    db.commit()
    return SyncActionResponse(mode=payload.mode, message="Sync completed", story=story_summary, subtasks=subtasks)


@router.post("/{jp_issue_id}/child", response_model=SyncIssueSummary)
def create_child_ticket(
    jp_issue_id: int,
    payload: ChildIssueCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> SyncIssueSummary:
    managed = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    if not managed:
        raise HTTPException(status_code=404, detail="Managed ticket not found")

    settings = get_system_settings_map(db)

    try:
        jp_issue = redmine.verify_jp_issue_resolved(
            jp_issue_id,
            settings.get("redmine_jp_host"),
            user_settings.redmine_jp_api_key_enc,
        )
        create_result = redmine.create_vn_ticket_resolved(
            vn_host=settings.get("redmine_vn_host"),
            vn_api_key_enc=user_settings.redmine_vn_api_key_enc,
            project_id=settings.get("redmine_vn_project_id"),
            jp_issue_id=jp_issue_id,
            jp_issue_url=f"{settings.get('redmine_jp_host', '').rstrip('/')}/issues/{jp_issue_id}",
            jp_subject=jp_issue.subject,
            subject=payload.subject,
            description=payload.description,
            assignee_id=payload.assignee_id,
            parent_issue_id=payload.parent_issue_id,
            related_ticket_id=payload.related_ticket_id,
            create_subtasks=[],
            description_template=settings.get("description_template"),
            main_tracker=payload.tracker,
        )
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    created_issue = create_result["story"]
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="create_child_ticket",
        target_type="managed_ticket",
        target_id=str(managed.id),
        payload_after=payload.model_dump(),
        **meta,
    )
    db.commit()
    return SyncIssueSummary(
        issue_id=created_issue.issue_id,
        subject=created_issue.subject,
        tracker=created_issue.tracker,
        url=created_issue.url,
    )


@router.get("/{jp_issue_id}", response_model=TicketDetailResponse)
def get_ticket_detail(jp_issue_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> TicketDetailResponse:
    _ = user
    ensure_ticket_follow_schema(db)
    managed = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    if not managed:
        raise HTTPException(status_code=404, detail="Managed ticket not found")
    settings = get_system_settings_map(db)
    user_settings = db.get(UserSettings, user.id)
    is_following = (
        db.query(UserManagedTicketFollow)
        .filter(UserManagedTicketFollow.user_id == user.id, UserManagedTicketFollow.managed_ticket_id == managed.id)
        .first()
        is not None
    )
    try:
        detail = redmine.build_ticket_detail(
            jp_issue_id=managed.jp_issue_id,
            vn_issue_id=managed.vn_issue_id,
            jp_host=settings.get("redmine_jp_host"),
            jp_api_key_enc=user_settings.redmine_jp_api_key_enc if user_settings else None,
            vn_host=settings.get("redmine_vn_host"),
            vn_api_key_enc=user_settings.redmine_vn_api_key_enc if user_settings else None,
        )
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TicketDetailResponse(
        managed_ticket_id=managed.id,
        jp_issue_id=managed.jp_issue_id,
        is_following=is_following,
        jp_info=TicketIssueSummary(**detail["jp"].__dict__),
        vn_issue=TicketIssueSummary(**detail["story"].__dict__),
        parent=TicketIssueSummary(**detail["parent"].__dict__) if detail["parent"] else None,
        children=[TicketIssueSummary(**item.__dict__) for item in detail["children"]],
        related=[TicketIssueSummary(**item.__dict__) for item in detail["related"]],
        links=[TicketLinkOut.model_validate(link) for link in managed.links],
    )


@router.delete("/{jp_issue_id}", response_model=MessageResponse)
def delete_managed_ticket(
    jp_issue_id: int,
    request: Request,
    actor: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    managed = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    if not managed:
        raise HTTPException(status_code=404, detail="Managed ticket not found")

    payload_before = {
        "managed_ticket_id": managed.id,
        "jp_issue_id": managed.jp_issue_id,
        "vn_issue_id": managed.vn_issue_id,
    }
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=actor,
        action="delete_managed_ticket",
        target_type="managed_ticket",
        target_id=str(managed.id),
        payload_before=payload_before,
        **meta,
    )
    db.delete(managed)
    db.commit()
    return MessageResponse(message="Managed ticket deleted")


@router.post("/{jp_issue_id}/follow", response_model=MessageResponse)
def follow_managed_ticket(
    jp_issue_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    managed = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    if not managed:
        raise HTTPException(status_code=404, detail="Managed ticket not found")

    ensure_ticket_follow(db, user_id=user.id, managed_ticket_id=managed.id)
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="follow_managed_ticket",
        target_type="managed_ticket",
        target_id=str(managed.id),
        payload_after={"jp_issue_id": jp_issue_id},
        **meta,
    )
    db.commit()
    return MessageResponse(message="Ticket followed")


@router.delete("/{jp_issue_id}/follow", response_model=MessageResponse)
def unfollow_managed_ticket(
    jp_issue_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    managed = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    if not managed:
        raise HTTPException(status_code=404, detail="Managed ticket not found")

    remove_ticket_follow(db, user_id=user.id, managed_ticket_id=managed.id)
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="unfollow_managed_ticket",
        target_type="managed_ticket",
        target_id=str(managed.id),
        payload_after={"jp_issue_id": jp_issue_id},
        **meta,
    )
    db.commit()
    return MessageResponse(message="Ticket unfollowed")


@router.put("/{jp_issue_id}/status-assignee", response_model=MessageResponse)
def update_status_assignee(
    jp_issue_id: int,
    payload: TicketStatusAssigneeUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> MessageResponse:
    managed = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    if not managed:
        raise HTTPException(status_code=404, detail="Managed ticket not found")
    settings = get_system_settings_map(db)
    try:
        field_names = payload.model_fields_set
        redmine.update_vn_issue_resolved(
            settings.get("redmine_vn_host"),
            user_settings.redmine_vn_api_key_enc,
            managed.vn_issue_id,
            status=payload.status,
            assignee=payload.assignee,
            project_id=settings.get("redmine_vn_project_id"),
            set_status="status" in field_names,
            set_assignee="assignee" in field_names,
        )
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="update_ticket_status_assignee",
        target_type="managed_ticket",
        target_id=str(managed.id),
        payload_after=payload.model_dump(exclude_none=True),
        **meta,
    )
    db.commit()
    return MessageResponse(message="Ticket updated")


@router.put("/issues/{issue_id}/status-assignee", response_model=MessageResponse)
def update_issue_status_assignee(
    issue_id: int,
    payload: TicketStatusAssigneeUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> MessageResponse:
    settings = get_system_settings_map(db)
    try:
        field_names = payload.model_fields_set
        redmine.update_vn_issue_resolved(
            settings.get("redmine_vn_host"),
            user_settings.redmine_vn_api_key_enc,
            issue_id,
            status=payload.status,
            assignee=payload.assignee,
            project_id=settings.get("redmine_vn_project_id"),
            set_status="status" in field_names,
            set_assignee="assignee" in field_names,
        )
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="update_issue_status_assignee",
        target_type="redmine_issue",
        target_id=str(issue_id),
        payload_after=payload.model_dump(exclude_none=True),
        **meta,
    )
    db.commit()
    return MessageResponse(message="Issue updated")


@router.post("/{jp_issue_id}/links", response_model=list[TicketLinkOut])
def upsert_ticket_link(
    jp_issue_id: int,
    payload: TicketLinkIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TicketLinkOut]:
    managed = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_issue_id).first()
    if not managed:
        raise HTTPException(status_code=404, detail="Managed ticket not found")
    duplicate = db.query(TicketLink).filter(TicketLink.url == payload.url, TicketLink.managed_ticket_id != managed.id).first()
    if duplicate:
        raise HTTPException(status_code=400, detail="URL already exists")
    link = None
    if payload.type in {"thread", "pr"}:
        link = db.query(TicketLink).filter(TicketLink.managed_ticket_id == managed.id, TicketLink.type == payload.type).first()
    if not link:
        link = db.query(TicketLink).filter(TicketLink.managed_ticket_id == managed.id, TicketLink.url == payload.url).first()
    derived_label = _derive_link_label(payload.type, payload.url, payload.label)
    if link:
        link.label = derived_label
        link.url = payload.url
        link.type = payload.type
    else:
        link = TicketLink(managed_ticket_id=managed.id, type=payload.type, label=derived_label, url=payload.url)
        db.add(link)
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="upsert_ticket_link",
        target_type="managed_ticket",
        target_id=str(managed.id),
        payload_after=payload.model_dump(),
        **meta,
    )
    db.commit()
    db.refresh(managed)
    return [TicketLinkOut.model_validate(item) for item in managed.links]


@router.put("/links/{link_id}", response_model=TicketLinkOut)
def update_ticket_link(
    link_id: int,
    payload: TicketLinkIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketLinkOut:
    link = db.query(TicketLink).filter(TicketLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    duplicate = (
        db.query(TicketLink)
        .filter(TicketLink.url == payload.url, TicketLink.id != link.id)
        .first()
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="URL already exists")

    link.type = payload.type
    link.url = payload.url
    link.label = _derive_link_label(payload.type, payload.url, payload.label)

    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="update_ticket_link",
        target_type="ticket_link",
        target_id=str(link.id),
        payload_after=payload.model_dump(),
        **meta,
    )
    db.commit()
    db.refresh(link)
    return TicketLinkOut.model_validate(link)


@router.delete("/links/{link_id}", response_model=MessageResponse)
def delete_ticket_link(
    link_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    link = db.query(TicketLink).filter(TicketLink.id == link_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="delete_ticket_link",
        target_type="ticket_link",
        target_id=str(link.id),
        payload_before={"id": link.id, "type": link.type, "url": link.url},
        **meta,
    )
    db.delete(link)
    db.commit()
    return MessageResponse(message="Link deleted")
