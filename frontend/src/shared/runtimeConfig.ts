type RuntimeConfig = {
  apiBase?: string;
  nodeServerBase?: string;
};

declare global {
  interface Window {
    CONTRACK_CONFIG?: RuntimeConfig;
  }
}

function configured(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function normalizeBase(value: string): string {
  return value.replace(/\/$/, "");
}

function defaultNodeServerBase(): string {
  return "http://127.0.0.1:3219";
}

export const apiBase = normalizeBase(
  configured(window.CONTRACK_CONFIG?.apiBase) ??
    configured(import.meta.env.VITE_API_BASE) ??
    "/api"
);

export const nodeServerBase = normalizeBase(
  configured(window.CONTRACK_CONFIG?.nodeServerBase) ??
    configured(import.meta.env.VITE_LOCAL_SERVER_BASE) ??
    defaultNodeServerBase()
);
