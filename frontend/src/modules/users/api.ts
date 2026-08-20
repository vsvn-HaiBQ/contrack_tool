import { http } from "../../shared/http";
import type { MenuPermission, Role, UserSettings } from "../../shared/types";

export const usersApi = {
  assignees: () => http<Array<{ id: number; name: string }>>("/users/assignees"),
  activities: () => http<string[]>("/users/activities"),
  statuses: (forceRefresh = false) =>
    http<Array<{ id: number; name: string }>>(`/users/statuses${forceRefresh ? "?force_refresh=true" : ""}`),
  trackers: () => http<Array<{ id: number; name: string }>>("/users/trackers"),
  mySettings: () => http<Partial<UserSettings>>("/users/me/settings"),
  updateMySettings: (payload: unknown) => http<Partial<UserSettings>>("/users/me/settings", { method: "PUT", body: JSON.stringify(payload) }),
  localPaths: () =>
    http<{
      build_source_folder?: string | null;
      build_output_folder?: string | null;
      git_eol_source_folder?: string | null;
    }>("/users/me/local-paths"),
  updateLocalPaths: (payload: unknown) =>
    http<{
      build_source_folder?: string | null;
      build_output_folder?: string | null;
      git_eol_source_folder?: string | null;
    }>("/users/me/local-paths", { method: "PUT", body: JSON.stringify(payload) }),
  changeMyPassword: (payload: { current_password: string; new_password: string }) =>
    http("/users/me/change-password", { method: "POST", body: JSON.stringify(payload) }),
  list: () => http<Array<{ id: number; username: string; role: string }>>("/users"),
  roles: () => http<{ items: Role[]; permissions: MenuPermission[] }>("/users/roles"),
  createRole: (payload: { name: string; permissions: string[] }) =>
    http<Role>("/users/roles", { method: "POST", body: JSON.stringify(payload) }),
  updateRole: (roleName: string, payload: { name: string; permissions: string[] }) =>
    http<Role>(`/users/roles/${encodeURIComponent(roleName)}`, { method: "PUT", body: JSON.stringify(payload) }),
  removeRole: (roleName: string) => http(`/users/roles/${encodeURIComponent(roleName)}`, { method: "DELETE" }),
  create: (payload: unknown) => http("/users", { method: "POST", body: JSON.stringify(payload) }),
  updateUserRole: (userId: number, role: string) =>
    http(`/users/${userId}/role`, { method: "PUT", body: JSON.stringify({ role }) }),
  resetPassword: (userId: number, password: string) =>
    http(`/users/${userId}/reset-password`, { method: "POST", body: JSON.stringify({ password }) }),
  remove: (userId: number) => http(`/users/${userId}`, { method: "DELETE" })
};
