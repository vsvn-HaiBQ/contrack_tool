import { HttpError } from "./http";
import { nodeServerBase } from "./runtimeConfig";

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

export const localServerApi = {
  health: () => localHttp<{ ok: boolean; service: string; port: number; default_paths: DefaultPaths }>("/health"),
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
  openPath: (targetPath: string) => localHttp<{ ok: boolean }>("/shell/open-path", jsonBody({ path: targetPath })),
  openContainingFolder: (targetPath: string) =>
    localHttp<{ ok: boolean }>("/shell/open-containing-folder", jsonBody({ path: targetPath })),
  validatePath: (targetPath: string, mustBeDirectory = true) =>
    localHttp<LocalPathValidation>("/filesystem/validate-path", jsonBody({ path: targetPath, mustBeDirectory })),
  build: {
    start: (payload: unknown) => localHttp<import("./types").BuildJob>("/build/start", jsonBody(payload)),
    getJob: (jobId: string) => localHttp<import("./types").BuildJob>(`/build/jobs/${encodeURIComponent(jobId)}`)
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
