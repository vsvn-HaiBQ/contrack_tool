from datetime import datetime
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageResponse(BaseModel):
    message: str


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_user_id: int | None = None
    actor_username: str
    action: str
    target_type: str
    target_id: str | None = None
    payload_before: dict | None = None
    payload_after: dict | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: datetime

    @field_validator("payload_before", "payload_after", mode="before")
    @classmethod
    def parse_legacy_json_payload(cls, value):
        if not isinstance(value, str):
            return value
        if not value.strip() or value.strip() == "null":
            return None
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"value": value}
        return parsed if isinstance(parsed, dict) else None

    @field_validator("ip", mode="before")
    @classmethod
    def stringify_ip(cls, value):
        return str(value) if value is not None else None


class AuditLogListResponse(BaseModel):
    items: list[AuditLogOut]
    total: int
    limit: int
    offset: int


class AuditLogOptionsResponse(BaseModel):
    actions: list[str]
    actor_usernames: list[str]
    target_types: list[str]


class AuditEventCreateRequest(BaseModel):
    action: str = Field(..., min_length=1, max_length=100)
    target_type: str = Field(..., min_length=1, max_length=50)
    target_id: str | None = Field(default=None, max_length=100)
    payload_after: dict | None = None


class AuditDeleteRequest(BaseModel):
    ids: list[int] = Field(default_factory=list)
    action: str | None = None
    actor_username: str | None = None
    target_type: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


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
    permissions: list[str] = Field(default_factory=list)
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
    role: str = "dev"


class UserRoleUpdateRequest(BaseModel):
    role: str


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class RoleCreateRequest(BaseModel):
    name: str
    permissions: list[str] = Field(default_factory=list)


class RoleUpdateRequest(BaseModel):
    name: str
    permissions: list[str] = Field(default_factory=list)


class MenuPermissionOut(BaseModel):
    key: str
    label: str


class RoleListResponse(BaseModel):
    items: list[RoleOut]
    permissions: list[MenuPermissionOut]


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequest(BaseModel):
    password: str


class DocumentTranslationSettingsIn(BaseModel):
    output_directory: str | None = None
    direction: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int | None = None
    batch_size: int | None = None
    context_window: int | None = None
    fast_mode: bool | None = None
    glossary: str | None = None
    instructions: str | None = None


class DocumentTranslationSettingsOut(BaseModel):
    output_directory: str | None = None
    direction: str | None = None
    model: str | None = None
    reasoning_effort: str | None = None
    timeout_seconds: int | None = None
    batch_size: int | None = None
    context_window: int | None = None
    fast_mode: bool | None = None
    glossary: str | None = None
    instructions: str | None = None


class UserSettingsIn(BaseModel):
    redmine_jp_api_key: str | None = None
    redmine_vn_api_key: str | None = None
    github_token: str | None = None
    team_automate_url: str | None = None
    default_assignee_id: int | None = None
    pinned_version_id: int | None = None
    document_translation: DocumentTranslationSettingsIn | None = None


class UserSettingsOut(BaseModel):
    redmine_jp_api_key: str | None = None
    redmine_vn_api_key: str | None = None
    github_token: str | None = None
    team_automate_url: str | None = None
    default_assignee_id: int | None = None
    pinned_version_id: int | None = None
    document_translation: DocumentTranslationSettingsOut = Field(default_factory=DocumentTranslationSettingsOut)


class LocalPathsIn(BaseModel):
    build_source_folder: str | None = None
    build_output_folder: str | None = None
    git_eol_source_folder: str | None = None


class LocalPathsOut(BaseModel):
    build_source_folder: str | None = None
    build_output_folder: str | None = None
    git_eol_source_folder: str | None = None


class SystemSettingsOut(BaseModel):
    values: dict[str, str | None]


class SystemSettingsUpdate(BaseModel):
    values: dict[str, str | None]


class VersionIn(BaseModel):
    name: str
    default_base_branch: str | None = None
    client_folder_id: str | None = None
    server_folder_id: str | None = None
    client_baseline_folder: str | None = None
    server_baseline_folder: str | None = None
    position: int | None = None


class VersionUpdate(BaseModel):
    name: str | None = None
    default_base_branch: str | None = None
    client_folder_id: str | None = None
    server_folder_id: str | None = None
    client_baseline_folder: str | None = None
    server_baseline_folder: str | None = None
    position: int | None = None


class VersionOut(BaseModel):
    id: int
    name: str
    default_base_branch: str | None = None
    client_folder_id: str | None = None
    server_folder_id: str | None = None
    client_baseline_folder: str | None = None
    server_baseline_folder: str | None = None
    position: int = 0
    updated_by: str | None = None


class VersionListResponse(BaseModel):
    items: list[VersionOut]


class PinVersionRequest(BaseModel):
    version_id: int | None = None


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


class IntegrationTestRequest(BaseModel):
    raw_value: str | None = None


class BoxSettingsIn(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    shared_link_access: str | None = None


class BoxSettingsOut(BaseModel):
    client_id: str | None = None
    client_secret_configured: bool = False
    shared_link_access: str = "company"
    updated_by: str | None = None


class BoxStatusResponse(BaseModel):
    configured: bool
    connected: bool
    message: str
    token_expires_at: datetime | None = None


class BoxOAuthStartResponse(BaseModel):
    authorize_url: str
    redirect_url: str


class BoxOAuthStartRequest(BaseModel):
    redirect_uri: str | None = None


class BoxUploadAccessResponse(BaseModel):
    access_token: str
    expires_at: datetime | None = None
    client_folder_id: str
    server_folder_id: str
    shared_link_access: str
    is_baseline: bool = False


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


class SyncSubtaskRequest(BaseModel):
    title: str
    assignee_id: int | None = None


class SyncActionRequest(BaseModel):
    jp_issue_id: int
    mode: str = Field(pattern="^(link|create_new)$")
    subject: str | None = None
    description: str | None = None
    assignee_id: int | None = None
    parent_issue_id: int | None = None
    related_ticket_id: int | None = None
    existing_vn_issue_id: int | None = None
    create_subtasks: list[SyncSubtaskRequest] = []
    extra_tracker: str | None = None
    force_create: bool = False


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


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    locked: bool
    position: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class NoteCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="")


class NoteUpdateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(default="")


class NoteReorderRequest(BaseModel):
    ids: list[int]


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


class TeamThreadPostResponse(BaseModel):
    url: str | None = None
    links: list[TicketLinkOut]


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
