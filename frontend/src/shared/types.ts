export type User = { id: number; username: string; role: string };

export type SetupStatus = { needs_setup: boolean; user_count: number };

export type Assignee = { id: number; name: string };
export type TrackerOption = { id: number; name: string };
export type IntegrationTestResult = { service: string; success: boolean; message: string };
export type StatusOption = { id: number; name: string };

export type IntegrationStatus = {
  service: string;
  configured: boolean;
  connected: boolean;
  message?: string | null;
};

export type TicketCandidate = {
  issue_id: number;
  subject: string;
  assignee?: string;
  tracker?: string;
  status?: string;
  url?: string;
  parent_issue_id?: number | null;
};

export type TicketLink = { id: number; type: string; label: string; url: string };

export type TicketDetail = {
  managed_ticket_id: number;
  jp_issue_id: number;
  is_following: boolean;
  jp_info: { issue_id: number; subject: string; tracker: string; status: string; assignee?: string; url: string };
  vn_issue: { issue_id: number; subject: string; tracker: string; status: string; allowed_statuses: string[]; assignee?: string; url: string };
  parent?: { issue_id: number; subject: string; tracker: string; status: string; allowed_statuses: string[]; assignee?: string; url: string } | null;
  children: Array<{ issue_id: number; subject: string; tracker: string; status: string; allowed_statuses: string[]; assignee?: string; url: string }>;
  related: Array<{ issue_id: number; subject: string; tracker: string; status: string; allowed_statuses: string[]; assignee?: string; url: string }>;
  links: TicketLink[];
};

export type ManagedTicketListItem = {
  managed_ticket_id: number;
  jp_issue_id: number;
  jp_url: string;
  vn_issue_id: number;
  vn_url: string;
  subject: string;
  status: string;
  assignee?: string;
  is_following: boolean;
};

export type SyncIssueSummary = { issue_id: number; subject: string; tracker: string; url: string };
export type SyncResult = { mode: string; message: string; story: SyncIssueSummary | null; subtasks: SyncIssueSummary[] };

export type LogtimeRow = {
  issue_id: number;
  subject: string;
  status: string;
  allowed_statuses: string[];
  activity: string;
  hours: number;
  url: string;
  assignee?: string | null;
  parent_issue_id?: number | null;
  tracker?: string | null;
};

export type LogtimeSaveResult = { issue_id: number; success: boolean; message: string };

export type PrResult = { title: string; url: string; linked_ticket_ids: number[] };
export type PrPreview = {
  title: string;
  source_branch: string;
  branch_exists: boolean;
  tickets: Array<{ issue_id: number; subject: string; url: string }>;
};

export type GitEolFilePreview = {
  path: string;
  old_path?: string | null;
  status: string;
  selected: boolean;
  processable: boolean;
  reason?: string | null;
  base_eol?: string | null;
  source_eol?: string | null;
  changed_lines: number;
  eol_only_lines: number;
};

export type GitEolPreview = {
  session_id: string;
  base_branch: string;
  source_branch: string;
  merge_base: string;
  files: GitEolFilePreview[];
};

export type GitEolFixResult = {
  session_id: string;
  fixed_files: Array<{
    path: string;
    restored_eol_lines: number;
    remaining_changed_lines: number;
    remaining_eol_only_lines: number;
    worktree_changed?: boolean;
    message?: string | null;
  }>;
  skipped_files: Array<{ path: string; reason: string }>;
  failed_files: Array<{ path: string; error: string }>;
  total_restored_eol_lines: number;
};

export type GitEolCommitResult = {
  session_id: string;
  committed: boolean;
  commit_sha?: string | null;
  message: string;
  changed_files: string[];
};

export type GitEolPushResult = {
  session_id: string;
  pushed: boolean;
  source_branch: string;
  message: string;
};

export type GitEolJobStatus = {
  job_id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
};

export type GitEolJobResponse = GitEolJobStatus & {
  error?: string | null;
  result?: GitEolPreview | null;
};

export type GitEolJobLog = {
  ts: number;
  level: "info" | "warn" | "error" | string;
  source: string;
  message: string;
};

export type GitEolDiffResponse = {
  session_id: string;
  path: string;
  diff: string;
};

export type GitEolDiffSide = {
  lineno: number | null;
  text: string | null;
  eol: "lf" | "crlf" | "cr" | "none" | null;
};

export type GitEolDiffRow = {
  type: "equal" | "eol" | "replace" | "delete" | "insert" | string;
  left: GitEolDiffSide | null;
  right: GitEolDiffSide | null;
};

export type GitEolStructuredDiff = {
  session_id: string;
  path: string;
  binary: boolean;
  rows: GitEolDiffRow[];
  stats: { added?: number; removed?: number; changed?: number; eol_only?: number };
};
