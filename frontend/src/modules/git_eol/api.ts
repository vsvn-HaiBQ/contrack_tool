import { http } from "../../shared/http";
import type {
  GitEolCommitResult,
  GitEolFixResult,
  GitEolJobLog,
  GitEolJobResponse,
  GitEolJobStatus,
  GitEolPushResult,
  GitEolStructuredDiff
} from "../../shared/types";

const API_BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/$/, "");

export const gitEolApi = {
  preview: (payload: unknown) =>
    http<GitEolJobStatus>("/git-eol/preview", { method: "POST", body: JSON.stringify(payload) }),
  job: (jobId: string) => http<GitEolJobResponse>(`/git-eol/jobs/${encodeURIComponent(jobId)}`),
  jobLogs: (jobId: string) =>
    http<GitEolJobLog[]>(`/git-eol/jobs/${encodeURIComponent(jobId)}/logs`),
  jobStreamUrl: (jobId: string) => `${API_BASE}/git-eol/jobs/${encodeURIComponent(jobId)}/stream`,
  diff: (sessionId: string, path: string) =>
    http<GitEolStructuredDiff>(
      `/git-eol/sessions/${encodeURIComponent(sessionId)}/sxs-diff?path=${encodeURIComponent(path)}`
    ),
  fix: (payload: unknown) => http<GitEolFixResult>("/git-eol/fix", { method: "POST", body: JSON.stringify(payload) }),
  commit: (payload: unknown) => http<GitEolCommitResult>("/git-eol/commit", { method: "POST", body: JSON.stringify(payload) }),
  push: (payload: unknown) => http<GitEolPushResult>("/git-eol/push", { method: "POST", body: JSON.stringify(payload) })
};
