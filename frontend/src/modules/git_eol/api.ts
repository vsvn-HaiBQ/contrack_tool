import { http } from "../../shared/http";
import { apiBase } from "../../shared/runtimeConfig";
import type {
  GitEolCommitResult,
  GitEolFixResult,
  GitEolJobLog,
  GitEolJobResponse,
  GitEolJobStatus,
  GitEolPushResult,
  GitEolStructuredDiff
} from "../../shared/types";

const API_BASE = apiBase;

type DiffOptions = {
  foldUnchanged?: boolean;
  includeFixed?: boolean;
  context?: number;
  leftStart?: number | null;
  leftEnd?: number | null;
  rightStart?: number | null;
  rightEnd?: number | null;
};

function diffUrl(sessionId: string, path: string, options: DiffOptions = {}) {
  const params = new URLSearchParams({ path });
  if (options.foldUnchanged) params.set("fold_unchanged", "true");
  if (options.includeFixed) params.set("include_fixed", "true");
  if (options.context !== undefined) params.set("context", String(options.context));
  if (options.leftStart) params.set("left_start", String(options.leftStart));
  if (options.leftEnd) params.set("left_end", String(options.leftEnd));
  if (options.rightStart) params.set("right_start", String(options.rightStart));
  if (options.rightEnd) params.set("right_end", String(options.rightEnd));
  return `/git-eol/sessions/${encodeURIComponent(sessionId)}/sxs-diff?${params.toString()}`;
}

export const gitEolApi = {
  preview: (payload: unknown) =>
    http<GitEolJobStatus>("/git-eol/preview", { method: "POST", body: JSON.stringify(payload) }),
  job: (jobId: string) => http<GitEolJobResponse>(`/git-eol/jobs/${encodeURIComponent(jobId)}`),
  jobLogs: (jobId: string) =>
    http<GitEolJobLog[]>(`/git-eol/jobs/${encodeURIComponent(jobId)}/logs`),
  jobStreamUrl: (jobId: string) => `${API_BASE}/git-eol/jobs/${encodeURIComponent(jobId)}/stream`,
  diff: (sessionId: string, path: string, options?: DiffOptions) =>
    http<GitEolStructuredDiff>(diffUrl(sessionId, path, options)),
  fix: (payload: unknown) => http<GitEolFixResult>("/git-eol/fix", { method: "POST", body: JSON.stringify(payload) }),
  commit: (payload: unknown) => http<GitEolCommitResult>("/git-eol/commit", { method: "POST", body: JSON.stringify(payload) }),
  push: (payload: unknown) => http<GitEolPushResult>("/git-eol/push", { method: "POST", body: JSON.stringify(payload) })
};
