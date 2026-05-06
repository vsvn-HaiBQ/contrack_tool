type RuntimeConfig = {
  apiBase?: string;
  nodeServerBase?: string;
  openXmlBase?: string;
  boxRedirectBase?: string;
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

function resolvedApiUrl(): URL {
  return new URL(apiBase, window.location.origin);
}

function apiCallbackPath(): string {
  const basePath = resolvedApiUrl().pathname.replace(/\/$/, "");
  return `${basePath}/box/oauth/callback`;
}

function defaultNodeServerBase(): string {
  return "http://127.0.0.1:3219";
}

function defaultOpenXmlBase(): string {
  const hostname = window.location.hostname || "127.0.0.1";
  return `http://${hostname}:5000`;
}

export const apiBase = normalizeBase(
  configured(window.CONTRACK_CONFIG?.apiBase) ??
    configured(import.meta.env.VITE_API_BASE) ??
    "/api"
);

export const apiBackendBase = (() => {
  const url = resolvedApiUrl();
  return `${url.protocol}//${url.host}`;
})();

export const apiBoxOAuthCallbackPath = apiCallbackPath();

export const nodeServerBase = normalizeBase(
  configured(window.CONTRACK_CONFIG?.nodeServerBase) ??
    configured(import.meta.env.VITE_LOCAL_SERVER_BASE) ??
    defaultNodeServerBase()
);

export const openXmlBase = normalizeBase(
  configured(window.CONTRACK_CONFIG?.openXmlBase) ??
    configured(import.meta.env.VITE_OPENXML_BASE) ??
    defaultOpenXmlBase()
);

// If an explicit HTTPS public base is set (hosted deployment), use it for the
// Box OAuth callback. Otherwise use the local Node server which runs on
// http://127.0.0.1 and is always accepted by Box as a valid redirect target.
const _boxRedirectBase = normalizeBase(
  configured(window.CONTRACK_CONFIG?.boxRedirectBase) ??
    configured(import.meta.env.VITE_BOX_REDIRECT_BASE) ??
    ""
);

export const boxOAuthRedirectUri = _boxRedirectBase
  ? new URL(apiCallbackPath(), `${_boxRedirectBase}/`).toString()
  : `${nodeServerBase}/box/oauth/callback`;
