from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.dependencies import get_current_user, request_meta
from app.models import ManagedTicket, TicketLink, User, UserSettings
from app.modules.github import provider as github
from app.modules.redmine import provider as redmine
from app.modules.tickets.service import ensure_ticket_follow
from app.modules.users.dependencies import get_current_user_settings
from app.schemas import PullRequestCreateRequest, PullRequestCreateResponse, PullRequestPreviewResponse, PullRequestPreviewTicket
from app.modules.audit.service import write_audit_log
from app.modules.settings.service import get_system_settings_map

router = APIRouter(prefix="/pull-requests", tags=["pull-requests"])


def _resolve_pr_preview(
    payload: PullRequestCreateRequest,
    db: Session,
) -> tuple[dict, str]:
    if not payload.jp_tickets:
        raise HTTPException(status_code=400, detail="jp_tickets is required")
    if not payload.base_branch.strip():
        raise HTTPException(status_code=400, detail="base_branch is required")
    if not payload.source_branch.strip():
        raise HTTPException(status_code=400, detail="source_branch is required")
    settings = get_system_settings_map(db)
    repo = settings.get("git_repo")
    if not repo:
        raise HTTPException(status_code=400, detail="Git repo is not configured")
    return settings, repo


@router.post("/preview", response_model=PullRequestPreviewResponse)
def preview_pull_request(
    payload: PullRequestCreateRequest,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> PullRequestPreviewResponse:
    _ = user
    settings, repo = _resolve_pr_preview(payload, db)
    try:
        tickets = [
            redmine.verify_jp_issue_resolved(ticket, settings.get("redmine_jp_host"), user_settings.redmine_jp_api_key_enc)
            for ticket in payload.jp_tickets
        ]
    except (redmine.IntegrationConfigError, redmine.RedmineClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        base_branch_exists = github.branch_exists_resolved(repo, payload.base_branch, user_settings.github_token_enc)
        if not base_branch_exists:
            raise HTTPException(status_code=400, detail="Base branch does not exist on remote")
        branch_exists = github.branch_exists_resolved(repo, payload.source_branch, user_settings.github_token_enc)
    except (github.IntegrationConfigError, github.GitHubClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    title = github.build_pr_title(payload.base_branch.strip(), payload.jp_tickets, [ticket.subject for ticket in tickets])
    return PullRequestPreviewResponse(
        title=title,
        source_branch=payload.source_branch.strip(),
        branch_exists=branch_exists,
        tickets=[PullRequestPreviewTicket(issue_id=ticket.issue_id, subject=ticket.subject, url=ticket.url) for ticket in tickets],
    )


@router.post("", response_model=PullRequestCreateResponse)
def create_pull_request(
    payload: PullRequestCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    user_settings: UserSettings = Depends(get_current_user_settings),
    db: Session = Depends(get_db),
) -> PullRequestCreateResponse:
    settings, repo = _resolve_pr_preview(payload, db)
    preview = preview_pull_request(payload, user, user_settings, db)
    if not preview.branch_exists:
        raise HTTPException(status_code=400, detail="Source branch does not exist on remote")
    pr_title = payload.title.strip() if payload.title and payload.title.strip() else preview.title
    try:
        template = github.pull_request_template_resolved(repo, user_settings.github_token_enc)
        body = template or github.build_pr_body(payload.jp_tickets, payload.source_branch.strip())
        created = github.create_pull_request_resolved(
            repo,
            title=pr_title,
            body=body,
            base=payload.base_branch.strip(),
            head=payload.source_branch.strip(),
            encrypted_token=user_settings.github_token_enc,
        )
    except (github.IntegrationConfigError, github.GitHubClientError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    linked_ticket_ids: list[int] = []
    for jp_ticket in payload.jp_tickets:
        managed = db.query(ManagedTicket).filter(ManagedTicket.jp_issue_id == jp_ticket).first()
        if not managed:
            continue
        link = db.query(TicketLink).filter(TicketLink.managed_ticket_id == managed.id, TicketLink.type == "pr").first()
        if not link:
            link = TicketLink(managed_ticket_id=managed.id, type="pr", label="Pull Request", url=created["url"])
            db.add(link)
        else:
            link.url = created["url"]
            link.label = "Pull Request"
        ensure_ticket_follow(db, user_id=user.id, managed_ticket_id=managed.id)
        linked_ticket_ids.append(managed.id)
    meta = request_meta(request)
    write_audit_log(
        db,
        actor=user,
        action="create_pr",
        target_type="pull_request",
        target_id=created["url"],
        payload_after=payload.model_dump(),
        **meta,
    )
    db.commit()
    return PullRequestCreateResponse(title=created["title"], url=created["url"], linked_ticket_ids=linked_ticket_ids)
