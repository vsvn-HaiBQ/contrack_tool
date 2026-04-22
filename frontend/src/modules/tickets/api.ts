import { http } from "../../shared/http";
import type { ManagedTicketListItem, SyncIssueSummary, SyncResult, TicketDetail } from "../../shared/types";

export const ticketsApi = {
  search: (jpIssueId: number) => http<{ exists: boolean; managed_ticket_id: number | null }>(`/tickets/search?jp_issue_id=${jpIssueId}`),
  verifySync: (payload: unknown) =>
    http<{ jp_issue_id: number; jp_subject: string; jp_issue_url: string; candidates: Array<{ issue_id: number; subject: string; assignee?: string; tracker?: string; status?: string; url?: string; parent_issue_id?: number | null }> }>(
      "/tickets/sync/verify",
      { method: "POST", body: JSON.stringify(payload) }
    ),
  sync: (payload: unknown) => http<SyncResult>("/tickets/sync", { method: "POST", body: JSON.stringify(payload) }),
  detail: (jpIssueId: number) => http<TicketDetail>(`/tickets/${jpIssueId}`),
  deleteManaged: (jpIssueId: number) => http(`/tickets/${jpIssueId}`, { method: "DELETE" }),
  managed: (scope: "following" | "all" = "following") => http<ManagedTicketListItem[]>(`/tickets/managed?scope=${scope}`),
  follow: (jpIssueId: number) => http(`/tickets/${jpIssueId}/follow`, { method: "POST" }),
  unfollow: (jpIssueId: number) => http(`/tickets/${jpIssueId}/follow`, { method: "DELETE" }),
  createChild: (jpIssueId: number, payload: unknown) =>
    http<SyncIssueSummary>(`/tickets/${jpIssueId}/child`, { method: "POST", body: JSON.stringify(payload) }),
  updateTicket: (jpIssueId: number, payload: unknown) =>
    http(`/tickets/${jpIssueId}/status-assignee`, { method: "PUT", body: JSON.stringify(payload) }),
  updateIssue: (issueId: number, payload: unknown) =>
    http(`/tickets/issues/${issueId}/status-assignee`, { method: "PUT", body: JSON.stringify(payload) }),
  upsertLink: (jpIssueId: number, payload: unknown) =>
    http(`/tickets/${jpIssueId}/links`, { method: "POST", body: JSON.stringify(payload) }),
  updateLink: (linkId: number, payload: unknown) =>
    http(`/tickets/links/${linkId}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteLink: (linkId: number) =>
    http(`/tickets/links/${linkId}`, { method: "DELETE" })
};
