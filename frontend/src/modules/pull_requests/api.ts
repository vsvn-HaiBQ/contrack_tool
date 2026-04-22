import { http } from "../../shared/http";
import type { PrPreview, PrResult } from "../../shared/types";

export const pullRequestsApi = {
  preview: (payload: unknown) => http<PrPreview>("/pull-requests/preview", { method: "POST", body: JSON.stringify(payload) }),
  create: (payload: unknown) => http<PrResult>("/pull-requests", { method: "POST", body: JSON.stringify(payload) })
};
