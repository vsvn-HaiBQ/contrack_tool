/// <reference types="vite/client" />

declare module "*.vue" {
  import type { DefineComponent } from "vue";
  const component: DefineComponent<object, object, unknown>;
  export default component;
}

type ElectronApiFetchInit = {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
};

type ElectronApiFetchResponse = {
  ok: boolean;
  status: number;
  statusText: string;
  headers: Record<string, string | null>;
  bodyText: string;
};

type ElectronBuildJobLog = {
  ts: number;
  level: string;
  source: string;
  message: string;
};

type ElectronBuildArtifact = {
  type: string;
  path: string;
  file_name: string;
};

type ElectronBuildJob = {
  job_id: string;
  status: "queued" | "running" | "succeeded" | "failed" | string;
  error: string | null;
  logs: ElectronBuildJobLog[];
  artifacts: ElectronBuildArtifact[];
  created_at: number;
  updated_at: number;
};

interface Window {
  contrackElectron?: {
    isElectron: true;
    getVersion: () => Promise<string>;
    getAllSettings: () => Promise<Record<string, unknown>>;
    getSetting: <T = unknown>(key: string) => Promise<T>;
    setSetting: <T = unknown>(key: string, value: T) => Promise<T>;
    getDefaultPaths: () => Promise<{ sourceFolder: string; buildFolder: string }>;
    selectDirectory: (currentPath?: string) => Promise<string | null>;
    openPath: (targetPath: string) => Promise<void>;
    apiFetch: (path: string, init?: ElectronApiFetchInit) => Promise<ElectronApiFetchResponse>;
    build: {
      start: (payload: unknown) => Promise<ElectronBuildJob>;
      getJob: (jobId: string) => Promise<ElectronBuildJob | null>;
    };
    gitEol: {
      previewWorkingTree: (payload: unknown) => Promise<import("./shared/types").GitEolPreview>;
      structuredDiff: (payload: unknown) => Promise<import("./shared/types").GitEolStructuredDiff>;
      fixWorkingTree: (payload: unknown) => Promise<import("./shared/types").GitEolFixResult>;
      commitWorkingTree: (payload: unknown) => Promise<import("./shared/types").GitEolCommitResult>;
      pushWorkingTree: (payload: unknown) => Promise<import("./shared/types").GitEolPushResult>;
    };
  };
}
