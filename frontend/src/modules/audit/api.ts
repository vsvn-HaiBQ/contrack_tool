import { http } from "../../shared/http";
import type { AuditLogListResponse } from "../../shared/types";

export type AuditFilters = {
  action?: string;
  actor_username?: string;
  target_type?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
};

function listQuery(filters: AuditFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && String(value).trim() !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export const auditApi = {
  list: (filters: AuditFilters) => http<AuditLogListResponse>(`/audit${listQuery(filters)}`),
  options: () => http<{ actions: string[]; actor_usernames: string[]; target_types: string[] }>("/audit/options"),
  record: (payload: unknown) => http("/audit/events", { method: "POST", body: JSON.stringify(payload) }),
  delete: (payload: unknown) => http<{ message: string }>("/audit", { method: "DELETE", body: JSON.stringify(payload) })
};
