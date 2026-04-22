import { http } from "../../shared/http";
import type { IntegrationStatus } from "../../shared/types";

export const settingsApi = {
  system: () => http<{ values: Record<string, string | null> }>("/settings/system"),
  updateSystem: (payload: unknown) => http("/settings/system", { method: "PUT", body: JSON.stringify(payload) }),
  integrationStatus: () => http<{ items: IntegrationStatus[] }>("/settings/integrations/status"),
  testIntegration: (serviceName: string) =>
    http<{ service: string; success: boolean; message: string }>(`/settings/integrations/test/${serviceName}`, { method: "POST" })
};
