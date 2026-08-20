from pydantic import BaseModel, Field


class GitEolPreviewRequest(BaseModel):
    base_branch: str
    source_branch: str


class GitEolFilePreview(BaseModel):
    path: str
    old_path: str | None = None
    status: str
    selected: bool = True
    processable: bool
    reason: str | None = None
    base_eol: str | None = None
    source_eol: str | None = None
    changed_lines: int = 0
    eol_only_lines: int = 0
    space_only_lines: int = 0


class GitEolPreviewResponse(BaseModel):
    session_id: str
    base_branch: str
    source_branch: str
    merge_base: str
    files: list[GitEolFilePreview]


class GitEolFixRequest(BaseModel):
    session_id: str
    files: list[str]
    fix_space_only: bool = False
    reset_existing: bool = False


class GitEolFixedFile(BaseModel):
    path: str
    restored_eol_lines: int
    fixed_eol_lines: list[int] = Field(default_factory=list)
    restored_space_only_lines: int = 0
    fixed_space_only_lines: list[int] = Field(default_factory=list)
    remaining_changed_lines: int
    remaining_eol_only_lines: int
    remaining_space_only_lines: int = 0
    worktree_changed: bool = False
    message: str | None = None


class GitEolSkippedFile(BaseModel):
    path: str
    reason: str


class GitEolFailedFile(BaseModel):
    path: str
    error: str


class GitEolFixResponse(BaseModel):
    session_id: str
    fixed_files: list[GitEolFixedFile]
    skipped_files: list[GitEolSkippedFile]
    failed_files: list[GitEolFailedFile]
    total_restored_eol_lines: int
    total_restored_space_only_lines: int = 0


class GitEolCommitRequest(BaseModel):
    session_id: str
    message: str | None = None


class GitEolCommitResponse(BaseModel):
    session_id: str
    committed: bool
    commit_sha: str | None = None
    message: str
    changed_files: list[str] = []


class GitEolPushRequest(BaseModel):
    session_id: str


class GitEolPushResponse(BaseModel):
    session_id: str
    pushed: bool
    source_branch: str
    message: str


class GitEolJobStatus(BaseModel):
    job_id: str
    kind: str
    status: str


class GitEolJobResponse(BaseModel):
    job_id: str
    kind: str
    status: str
    error: str | None = None
    result: GitEolPreviewResponse | None = None


class GitEolJobLog(BaseModel):
    ts: float
    level: str
    source: str
    message: str


class GitEolDiffResponse(BaseModel):
    session_id: str
    path: str
    diff: str


class GitEolDiffSide(BaseModel):
    lineno: int | None = None
    text: str | None = None
    eol: str | None = None


class GitEolDiffRow(BaseModel):
    type: str  # equal | eol | fixed_eol | fixed_space | replace | delete | insert | fold
    left: GitEolDiffSide | None = None
    right: GitEolDiffSide | None = None
    count: int | None = None
    left_start: int | None = None
    left_end: int | None = None
    right_start: int | None = None
    right_end: int | None = None


class GitEolStructuredDiffResponse(BaseModel):
    session_id: str
    path: str
    binary: bool = False
    rows: list[GitEolDiffRow] = []
    stats: dict[str, int] = {}
