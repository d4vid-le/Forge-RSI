const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? "";

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object") {
    const d = detail as Record<string, unknown>;
    if (typeof d.error === "string") return d.error;
    if (typeof d.message === "string") return d.message;
    if (Array.isArray(d.detail) && d.detail[0] && typeof d.detail[0] === "object") {
      const first = d.detail[0] as Record<string, unknown>;
      if (typeof first.msg === "string") return first.msg;
    }
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...(init?.headers || {}) },
  });
  let body: unknown = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) {
    const detail = body && typeof body === "object" && "detail" in body
      ? (body as Record<string, unknown>).detail
      : body;
    throw new ApiError(res.status, detail, detailMessage(detail, `HTTP ${res.status} ${res.statusText}`));
  }
  const obj = body as Record<string, unknown> | null;
  if (obj && obj.ok === false && typeof obj.error === "string") {
    throw new ApiError(res.status, obj, obj.error);
  }
  return body as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
};

export function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
