import { http } from "./http";
import { apiBase } from "./runtimeConfig";
import type { LocalServerDownloadTicket, LocalServerReleaseManifest } from "./types";

export const localServerReleaseApi = {
  latest: () => http<LocalServerReleaseManifest>("/local-server/releases/latest"),
  createDownloadTicket: (version: string) =>
    http<LocalServerDownloadTicket>(`/local-server/releases/${encodeURIComponent(version)}/download-ticket`, {
      method: "POST"
    })
};

export function absoluteBackendUrl(pathOrUrl: string): string {
  if (/^https?:\/\//i.test(pathOrUrl)) {
    return pathOrUrl;
  }
  const apiUrl = new URL(apiBase, window.location.origin);
  return new URL(pathOrUrl, apiUrl.origin).toString();
}
