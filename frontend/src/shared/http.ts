const API_BASE = (import.meta.env.VITE_API_BASE ?? "/api").replace(/\/$/, "");

const STATUS_FALLBACKS: Record<number, string> = {
  400: "Yêu cầu không hợp lệ",
  401: "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại",
  403: "Bạn không có quyền thực hiện hành động này",
  404: "Không tìm thấy dữ liệu",
  409: "Dữ liệu đã tồn tại hoặc đang xung đột",
  422: "Dữ liệu nhập chưa hợp lệ",
  429: "Quá nhiều yêu cầu, vui lòng thử lại sau",
  500: "Hệ thống đang gặp sự cố, vui lòng thử lại",
  502: "Dịch vụ bên ngoài không phản hồi",
  503: "Hệ thống tạm thời không khả dụng",
  504: "Thao tác bị quá thời gian chờ"
};

function pickMessage(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (Array.isArray(detail) && detail.length) {
      // FastAPI 422 -> [{loc, msg, type}]
      const first = detail[0];
      if (first && typeof first === "object" && typeof (first as { msg?: string }).msg === "string") {
        return (first as { msg: string }).msg;
      }
    }
    const message = (body as { message?: unknown }).message;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  return STATUS_FALLBACKS[status] ?? "Yêu cầu thất bại";
}

export class HttpError extends Error {
  status: number;
  requestId?: string;
  constructor(status: number, message: string, requestId?: string) {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.requestId = requestId;
  }
}

function plainHeaders(headers: HeadersInit | undefined): Record<string, string> {
  if (!headers) {
    return {};
  }
  if (headers instanceof Headers) {
    const result: Record<string, string> = {};
    headers.forEach((value, key) => {
      result[key] = value;
    });
    return result;
  }
  if (Array.isArray(headers)) {
    return Object.fromEntries(headers);
  }
  return headers;
}

async function electronHttp<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await window.contrackElectron!.apiFetch(path, {
    method: init?.method,
    headers: {
      "Content-Type": "application/json",
      ...plainHeaders(init?.headers)
    },
    body: typeof init?.body === "string" ? init.body : undefined
  });
  let body: unknown = null;
  if (response.bodyText) {
    try {
      body = JSON.parse(response.bodyText);
    } catch {
      body = response.bodyText;
    }
  }
  if (!response.ok) {
    throw new HttpError(response.status, pickMessage(body, response.status), response.headers["x-request-id"] ?? undefined);
  }
  if (response.status === 204 || response.bodyText === "") {
    return undefined as T;
  }
  return body as T;
}

export async function http<T>(path: string, init?: RequestInit): Promise<T> {
  if (window.contrackElectron?.apiFetch) {
    return electronHttp<T>(path, init);
  }
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    ...init
  });
  if (!response.ok) {
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    const message = pickMessage(body, response.status) || response.statusText || "Yêu cầu thất bại";
    throw new HttpError(response.status, message, response.headers.get("X-Request-ID") ?? undefined);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return response.json() as Promise<T>;
}
