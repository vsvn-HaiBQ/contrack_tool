import { http } from "../../shared/http";

export const usersApi = {
  assignees: () => http<Array<{ id: number; name: string }>>("/users/assignees"),
  activities: () => http<string[]>("/users/activities"),
  statuses: (forceRefresh = false) =>
    http<Array<{ id: number; name: string }>>(`/users/statuses${forceRefresh ? "?force_refresh=true" : ""}`),
  trackers: () => http<Array<{ id: number; name: string }>>("/users/trackers"),
  mySettings: () => http<{ redmine_jp_api_key?: string; redmine_vn_api_key?: string; github_token?: string; default_assignee_id?: number }>("/users/me/settings"),
  updateMySettings: (payload: unknown) => http("/users/me/settings", { method: "PUT", body: JSON.stringify(payload) }),
  changeMyPassword: (payload: { current_password: string; new_password: string }) =>
    http("/users/me/change-password", { method: "POST", body: JSON.stringify(payload) }),
  list: () => http<Array<{ id: number; username: string; role: string }>>("/users"),
  create: (payload: unknown) => http("/users", { method: "POST", body: JSON.stringify(payload) }),
  resetPassword: (userId: number, password: string) =>
    http(`/users/${userId}/reset-password`, { method: "POST", body: JSON.stringify({ password }) }),
  remove: (userId: number) => http(`/users/${userId}`, { method: "DELETE" })
};
