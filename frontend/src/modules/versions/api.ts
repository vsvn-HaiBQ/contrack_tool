import { http } from "../../shared/http";
import type { Version } from "../../shared/types";

export const versionsApi = {
  list: () => http<{ items: Version[] }>("/versions"),
  create: (payload: Partial<Version>) =>
    http<Version>("/versions", { method: "POST", body: JSON.stringify(payload) }),
  update: (id: number, payload: Partial<Version>) =>
    http<Version>(`/versions/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  remove: (id: number) => http(`/versions/${id}`, { method: "DELETE" }),
  pin: (versionId: number | null) =>
    http<Version | null>("/versions/pin", { method: "POST", body: JSON.stringify({ version_id: versionId }) }),
};
