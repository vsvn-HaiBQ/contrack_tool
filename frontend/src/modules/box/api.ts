import { http } from "../../shared/http";
import type { BoxSettings, BoxStatus, BoxUploadAccess } from "../../shared/types";

export const boxApi = {
  settings: () => http<BoxSettings>("/box/settings"),
  updateSettings: (payload: unknown) => http<BoxSettings>("/box/settings", { method: "PUT", body: JSON.stringify(payload) }),
  status: () => http<BoxStatus>("/box/status"),
  startOAuth: (payload: unknown) =>
    http<{ authorize_url: string; redirect_url: string }>("/box/oauth/start", { method: "POST", body: JSON.stringify(payload) }),
  uploadAccess: (targetBranch?: string | null) => {
    const query = targetBranch?.trim() ? `?target_branch=${encodeURIComponent(targetBranch.trim())}` : "";
    return http<BoxUploadAccess>(`/box/upload-access${query}`, { method: "POST" });
  }
};
