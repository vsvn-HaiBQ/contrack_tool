import { http } from "../../shared/http";

export const authApi = {
  me: () => http<{ authenticated: boolean; needs_setup: boolean; user: { id: number; username: string; role: string } | null }>("/auth/me"),
  login: (payload: { username: string; password: string }) => http("/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  logout: () => http("/auth/logout", { method: "POST" }),
  setupStatus: () => http<{ needs_setup: boolean; user_count: number }>("/auth/setup-status"),
  setup: (payload: { username: string; password: string }) => http("/auth/setup", { method: "POST", body: JSON.stringify(payload) })
};
