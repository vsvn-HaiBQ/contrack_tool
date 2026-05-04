import { http } from "../../shared/http";
import type { ClientUpdateInfo } from "../../shared/types";

export const updatesApi = {
  check: (currentVersion?: string | null) => {
    const query = currentVersion ? `?current_version=${encodeURIComponent(currentVersion)}` : "";
    return http<ClientUpdateInfo>(`/checkupdate${query}`);
  }
};
