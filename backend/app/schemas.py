from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MessageResponse(BaseModel):
    message: str


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupAdminRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    role: str
    created_at: datetime


class MeResponse(BaseModel):
    authenticated: bool
    needs_setup: bool = False
    user: UserOut | None = None


class SetupStatusResponse(BaseModel):
    needs_setup: bool
    user_count: int


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    password: str


class UserSettingsIn(BaseModel):
    redmine_jp_api_key: str | None = None
    redmine_vn_api_key: str | None = None
    github_token: str | None = None
    default_assignee_id: int | None = None


class UserSettingsOut(BaseModel):
    redmine_jp_api_key: str | None = None
    redmine_vn_api_key: str | None = None
    github_token: str | None = None
    default_assignee_id: int | None = None


class SystemSettingsOut(BaseModel):
    values: dict[str, str | None]


class SystemSettingsUpdate(BaseModel):
    values: dict[str, str | None]


class IntegrationStatusItem(BaseModel):
    service: str
    configured: bool
    connected: bool
    message: str | None = None


class IntegrationStatusResponse(BaseModel):
    items: list[IntegrationStatusItem]


class IntegrationTestResponse(BaseModel):
    service: str
    success: bool
    message: str


class AssigneeOption(BaseModel):
    id: int
    name: str


class TrackerOption(BaseModel):
    id: int
    name: str


class VerifySyncRequest(BaseModel):
    jp_issue_id: int | None = None
    jp_issue_url: str | None = None


class VNTicketReference(BaseModel):
    issue_id: int
    subject: str
    assignee: str | None = None
    tracker: str | None = None
    status: str | None = None
    url: str | None = None
    parent_issue_id: int | None = None


class VerifySyncResponse(BaseModel):
    jp_issue_id: int
    jp_subject: str
    jp_issue_url: str
    candidates: list[VNTicketReference]


class SyncActionRequest(BaseModel):
    jp_issue_id: int
    mode: str = Field(pattern="^(link|create_new)$")
    subject: str | None = None
    description: str | None = None
    assignee_id: int | None = None
    parent_issue_id: int | None = None
    related_ticket_id: int | None = None
    existing_vn_issue_id: int | None = None
    create_subtasks: list[str] = []
    extra_tracker: str | None = None


class ChildIssueCreateRequest(BaseModel):
    parent_issue_id: int
    subject: str
    description: str | None = None
    assignee_id: int | None = None
    related_ticket_id: int | None = None
    tracker: str | None = None


class SyncIssueSummary(BaseModel):
    issue_id: int
    subject: str
    tracker: str
    url: str


class SyncActionResponse(BaseModel):
    mode: str
    message: str
    story: SyncIssueSummary | None = None
    subtasks: list[SyncIssueSummary] = []


class ManagedTicketListItem(BaseModel):
    managed_ticket_id: int
    jp_issue_id: int
    jp_url: str
    vn_issue_id: int
    vn_url: str
    subject: str
    status: str
    assignee: str | None = None
    is_following: bool = False


class TicketLinkIn(BaseModel):
    type: str
    label: str | None = None
    url: str


class TicketLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    label: str
    url: str


class TicketIssueSummary(BaseModel):
    issue_id: int
    subject: str
    tracker: str
    status: str
    allowed_statuses: list[str] = []
    assignee: str | None = None
    url: str


class TicketDetailResponse(BaseModel):
    managed_ticket_id: int
    jp_issue_id: int
    is_following: bool = False
    jp_info: TicketIssueSummary
    vn_issue: TicketIssueSummary
    parent: TicketIssueSummary | None = None
    children: list[TicketIssueSummary]
    related: list[TicketIssueSummary]
    links: list[TicketLinkOut]


class TicketStatusAssigneeUpdate(BaseModel):
    status: str | None = None
    assignee: str | None = None


class LogtimeRow(BaseModel):
    issue_id: int
    subject: str
    status: str
    allowed_statuses: list[str] = []
    activity: str
    hours: float
    url: str
    assignee: str | None = None
    parent_issue_id: int | None = None
    tracker: str | None = None


class LogtimeSourceResponse(BaseModel):
    date: str
    rows: list[LogtimeRow]
    activities: list[str]


class LogtimeSaveRow(BaseModel):
    issue_id: int
    activity: str
    hours: float


class LogtimeSaveRequest(BaseModel):
    date: str
    rows: list[LogtimeSaveRow]


class LogtimeSaveResult(BaseModel):
    issue_id: int
    success: bool
    message: str


class PullRequestCreateRequest(BaseModel):
    jp_tickets: list[int]
    base_branch: str
    source_branch: str
    title: str | None = None


class PullRequestPreviewTicket(BaseModel):
    issue_id: int
    subject: str
    url: str


class PullRequestPreviewResponse(BaseModel):
    title: str
    source_branch: str
    branch_exists: bool
    tickets: list[PullRequestPreviewTicket]


class PullRequestCreateResponse(BaseModel):
    title: str
    url: str
    linked_ticket_ids: list[int]
