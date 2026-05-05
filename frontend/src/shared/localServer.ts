import { HttpError } from "./http";
import { nodeServerBase, openXmlBase } from "./runtimeConfig";
import type { LocalServerHealth, LocalServerUpdateCheck, LocalServerUpdateInstallResult } from "./types";

export const localServerBase = nodeServerBase;

type SettingResponse<T> = {
  key: string;
  value: T | null;
};

type DefaultPaths = {
  sourceFolder: string;
  buildFolder: string;
};

export type LocalPathValidation = {
  path: string;
  exists: boolean;
  is_directory: boolean;
  is_file: boolean;
  valid: boolean;
  message: string;
};

export type CodexModelOption = {
  slug: string;
  display_name: string;
  description?: string;
  default_reasoning_level?: string;
  supported_reasoning_levels?: Array<{ effort: string; description?: string }>;
  additional_speed_tiers?: string[];
};

function messageFromBody(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const message = (body as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  return fallback;
}

async function localHttp<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${localServerBase}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {})
      },
      ...init
    });
  } catch (error) {
    throw new Error(`Node processing server is not reachable at ${localServerBase}. Start the Node server and retry.`);
  }

  let body: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }

  if (!response.ok) {
    throw new HttpError(response.status, messageFromBody(body, response.statusText || "Local server request failed"));
  }
  return body as T;
}

function jsonBody(payload: unknown): RequestInit {
  return {
    method: "POST",
    body: JSON.stringify(payload)
  };
}

function withOpenXmlBase(payload: unknown): Record<string, unknown> {
  const body = payload && typeof payload === "object" && !Array.isArray(payload)
    ? { ...(payload as Record<string, unknown>) }
    : {};
  const configured = body.openxml_base_url ?? body.openXmlBaseUrl;
  return {
    ...body,
    openxml_base_url: typeof configured === "string" && configured.trim() ? configured : openXmlBase
  };
}

function withOpenXmlQuery(path: string): string {
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}openxml_base_url=${encodeURIComponent(openXmlBase)}`;
}

export const localServerApi = {
  health: () => localHttp<LocalServerHealth>("/health"),
  updates: {
    status: () => localHttp<LocalServerUpdateCheck>("/updates/status"),
    check: (payload: unknown) => localHttp<LocalServerUpdateCheck>("/updates/check", jsonBody(payload)),
    install: (payload: unknown) => localHttp<LocalServerUpdateInstallResult>("/updates/install", jsonBody(payload))
  },
  defaultPaths: () => localHttp<DefaultPaths>("/settings/default-paths"),
  getSetting: async <T = unknown>(key: string) => {
    const response = await localHttp<SettingResponse<T>>(`/settings/${encodeURIComponent(key)}`);
    return response.value;
  },
  setSetting: async <T = unknown>(key: string, value: T) => {
    const response = await localHttp<SettingResponse<T>>(`/settings/${encodeURIComponent(key)}`, {
      method: "PUT",
      body: JSON.stringify({ value })
    });
    return response.value;
  },
  selectDirectory: async (currentPath?: string) => {
    const response = await localHttp<{ path: string | null }>("/dialog/select-directory", jsonBody({ currentPath }));
    return response.path;
  },
  selectFile: async (currentPath?: string) => {
    const response = await localHttp<{ path: string | null }>("/dialog/select-file", jsonBody({ currentPath }));
    return response.path;
  },
  openPath: (targetPath: string) => localHttp<{ ok: boolean }>("/shell/open-path", jsonBody({ path: targetPath })),
  openContainingFolder: (targetPath: string) =>
    localHttp<{ ok: boolean }>("/shell/open-containing-folder", jsonBody({ path: targetPath })),
  validatePath: (targetPath: string, mustBeDirectory = true) =>
    localHttp<LocalPathValidation>("/filesystem/validate-path", jsonBody({ path: targetPath, mustBeDirectory })),
  build: {
    start: (payload: unknown) => localHttp<import("./types").BuildJob>("/build/start", jsonBody(payload)),
    getJob: (jobId: string) => localHttp<import("./types").BuildJob>(`/build/jobs/${encodeURIComponent(jobId)}`)
  },
  documentTranslation: {
    health: () =>
      localHttp<{
        ok: boolean;
        openxml: { ok: boolean; base_url: string; message: string };
        codex: { ok: boolean; command: string; message: string; version?: string };
        defaults: Record<string, unknown>;
      }>(withOpenXmlQuery("/document-translation/health")),
    models: async () => {
      const response = await localHttp<{ models: CodexModelOption[] }>("/document-translation/models");
      return response.models;
    },
    sheets: async (payload: unknown) => {
      const response = await localHttp<{ sheets: string[] }>("/document-translation/sheets", jsonBody(withOpenXmlBase(payload)));
      return response.sheets;
    },
    extract: (payload: unknown) =>
      localHttp<{ file_path: string; extension: string; file_type?: string; sheets: string[]; segment_count: number; segments: string[] }>(
        "/document-translation/extract",
        jsonBody(withOpenXmlBase(payload))
      ),
    start: (payload: unknown) =>
      localHttp<import("./types").DocumentTranslationJob>("/document-translation/translate", jsonBody(withOpenXmlBase(payload))),
    getJob: (jobId: string) =>
      localHttp<import("./types").DocumentTranslationJob>(`/document-translation/jobs/${encodeURIComponent(jobId)}`)
  },
  gitEol: {
    previewWorkingTree: (payload: unknown) =>
      localHttp<import("./types").GitEolPreview>("/git-eol/working-tree/preview", jsonBody(payload)),
    structuredDiff: (payload: unknown) =>
      localHttp<import("./types").GitEolStructuredDiff>("/git-eol/working-tree/structured-diff", jsonBody(payload)),
    fixWorkingTree: (payload: unknown) =>
      localHttp<import("./types").GitEolFixResult>("/git-eol/working-tree/fix", jsonBody(payload)),
    commitWorkingTree: (payload: unknown) =>
      localHttp<import("./types").GitEolCommitResult>("/git-eol/working-tree/commit", jsonBody(payload)),
    pushWorkingTree: (payload: unknown) =>
      localHttp<import("./types").GitEolPushResult>("/git-eol/working-tree/push", jsonBody(payload))
  }
};
