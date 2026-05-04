const { getApiBaseUrl, readSettings, writeSettings } = require("./settings.cjs");

function normalizeBaseUrl(value) {
  const raw = String(value || "http://localhost:8009/api").trim().replace(/\/$/, "");
  try {
    const url = new URL(raw);
    if (url.pathname === "" || url.pathname === "/") {
      url.pathname = "/api";
    }
    return url.toString().replace(/\/$/, "");
  } catch {
    return raw;
  }
}

function cookieHeader(cookies) {
  return Object.entries(cookies || {})
    .filter(([, value]) => typeof value === "string" && value.length > 0)
    .map(([key, value]) => `${key}=${value}`)
    .join("; ");
}

function persistSetCookie(headers) {
  const getSetCookie = headers.getSetCookie ? headers.getSetCookie.bind(headers) : null;
  const rawCookies = getSetCookie ? getSetCookie() : [];
  const single = headers.get("set-cookie");
  if (single && rawCookies.length === 0) {
    rawCookies.push(single);
  }
  if (!rawCookies.length) {
    return;
  }
  const settings = readSettings();
  settings.cookies = settings.cookies || {};
  for (const raw of rawCookies) {
    const first = String(raw).split(";")[0];
    const separator = first.indexOf("=");
    if (separator <= 0) {
      continue;
    }
    const name = first.slice(0, separator).trim();
    const value = first.slice(separator + 1);
    if (value) {
      settings.cookies[name] = value;
    } else {
      delete settings.cookies[name];
    }
  }
  writeSettings(settings);
}

async function apiFetch({ path, init } = {}) {
  const baseUrl = normalizeBaseUrl(getApiBaseUrl());
  const requestPath = String(path || "");
  const url = requestPath.startsWith("http://") || requestPath.startsWith("https://")
    ? requestPath
    : `${baseUrl}${requestPath.startsWith("/") ? requestPath : `/${requestPath}`}`;
  const settings = readSettings();
  const headers = {
    "Content-Type": "application/json",
    ...((init && init.headers) || {}),
  };
  const cookies = cookieHeader(settings.cookies);
  if (cookies) {
    headers.Cookie = cookies;
  }

  let response;
  try {
    response = await fetch(url, {
      method: (init && init.method) || "GET",
      headers,
      body: init && init.body ? init.body : undefined,
      redirect: "manual",
    });
  } catch (error) {
    const detail = `Không kết nối được server API tại ${baseUrl}. Vui lòng kiểm tra backend đang chạy hoặc cấu hình biến môi trường CONTRACK_API_BASE.`;
    return {
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      headers: {
        "content-type": "application/json",
        "x-request-id": null,
      },
      bodyText: JSON.stringify({ detail, cause: error && error.message ? error.message : String(error) }),
    };
  }
  persistSetCookie(response.headers);
  const bodyText = await response.text();
  return {
    ok: response.ok,
    status: response.status,
    statusText: response.statusText,
    headers: {
      "content-type": response.headers.get("content-type"),
      "x-request-id": response.headers.get("x-request-id"),
    },
    bodyText,
  };
}

module.exports = { apiFetch };
