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
